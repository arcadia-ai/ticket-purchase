"""核心抢票工作流编排。"""
import time
from dataclasses import dataclass, field

import yaml
from loguru import logger

from .detector import Detector
from .executor import Executor
from .log import take_screenshot
from .monitor import ensure_damai_running, wait_for_element
from .recovery import RecoveryManager


@dataclass
class TicketConfig:
    """从 YAML 加载的购票配置。"""
    keyword: str  # 搜索关键词
    city: str = ""  # 观演城市，如 "长沙"、"北京"
    session: str = ""  # 场次关键词，如 "周六" "20:00"，为空则选第一个可购买场次
    price_index: int = 0  # 票档索引，0 为第一档
    users: list = field(default_factory=lambda: [])  # 观演人姓名列表
    target_time: str = ""  # 开抢时间，为空则立即执行
    if_commit_order: bool = True  # 是否提交订单
    max_retry: int = 3  # 最大重试次数

    @staticmethod
    def load(path: str) -> "TicketConfig":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        # 过滤已知字段，警告未知键
        known = set(TicketConfig.__dataclass_fields__)
        unknown = set(data) - known
        if unknown:
            logger.warning("未知配置项已忽略: {}", unknown)
        return TicketConfig(**{k: v for k, v in data.items() if k in known})


class TicketWorkflow:
    """编排完整的抢票流程。"""

    # 页面状态定义：步骤名 -> 页面特征关键词
    PAGE_SIGNATURES = {
        "首页": ["首页", "推荐", "搜索演出"],
        "搜索页": ["搜索", "取消", "历史"],
        "搜索结果": ["搜索结果", "演出", "场次"],
        "演出详情": ["预定", "预约", "立即购买", "场次", "票档"],
        "城市选择": ["城市", "全国", "北京", "上海"],
        "观演人弹窗": ["观演人", "预选", "知道了"],
        "场次选择": ["场次", "有票", "预售", "售罄"],
        "票档选择": ["票档", "价格", "¥", "缺货"],
        "数量选择": ["数量", "张", "+", "-"],
        "确认订单": ["确认", "订单", "提交", "支付"],
        "支付页面": ["支付", "付款", "微信", "支付宝"],
    }

    def __init__(self, device, config: TicketConfig):
        self.device = device
        self.config = config
        self.detector = Detector(device)
        self.executor = Executor(device)
        # 共享 LLM client 给 recovery 模块
        self.recovery = RecoveryManager(device, llm_client=self.detector._llm)
        self._current_step_index = 0

    def run(self) -> bool:
        """执行完整的抢票流程。

        订单提交成功返回 True。
        """
        logger.info("=" * 50)
        logger.info("开始执行抢票流程")
        logger.info("关键词: {}, 城市: {}, 场次: {}, 购票人: {}",
                    self.config.keyword, self.config.city or "自动",
                    self.config.session or "自动", self.config.users)
        logger.info("=" * 50)

        start_time = time.time()
        self.recovery.start_popup_watcher()

        try:
            steps = [
                ("启动应用", self._step_launch_app),
                ("搜索演出", self._step_search_event),
                ("选择城市", self._step_select_city),
                ("处理观演人弹窗", self._step_handle_viewer_popup),
                ("点击预定", self._step_click_buy),
                ("选择场次", self._step_select_session),
                ("选择票档", self._step_select_price),
                ("选择张数", self._step_select_quantity),
                ("点击确定", self._step_confirm_purchase),
                ("提交订单", self._step_submit_order),
            ]

            for idx, (step_name, step_func) in enumerate(steps):
                self._current_step_index = idx
                logger.info("--- {} ---", step_name)

                # 检测当前页面状态，确保与预期步骤同步
                if not self._verify_page_state(step_name, steps):
                    logger.error("页面状态异常，无法继续执行: {}", step_name)
                    take_screenshot(self.device, f"page_mismatch_{step_name.replace(' ', '_')}")
                    return False

                success = self.recovery.retry_step(step_func, step_name)
                if not success:
                    logger.error("步骤失败: {}", step_name)
                    take_screenshot(self.device, f"fail_{step_name.replace(' ', '_')}")
                    return False
                take_screenshot(self.device, f"step_{step_name.replace(' ', '_')}")

            elapsed = time.time() - start_time
            logger.info("=" * 50)
            logger.info("流程完成，耗时 {:.1f}秒", elapsed)
            logger.info("=" * 50)
            return True

        except Exception as e:
            logger.error("意外错误: {}", e)
            take_screenshot(self.device, "exception")
            return False
        finally:
            self.recovery.stop_popup_watcher()

    def run_with_retry(self) -> bool:
        """带整体重试逻辑的流程执行。"""
        for attempt in range(1, self.config.max_retry + 1):
            logger.info("第 {}/{} 次尝试", attempt, self.config.max_retry)
            if self.run():
                logger.info("抢票成功！")
                return True

            if attempt < self.config.max_retry:
                logger.info("2秒后重试...")
                time.sleep(2)
                # 按返回键重置状态
                self.recovery.press_back_to_recover()

        logger.error("全部 {} 次尝试均失败", self.config.max_retry)
        return False

    # === 页面状态检测 ===

    # 可选步骤（没有对应弹窗/页面时自动跳过）
    OPTIONAL_STEPS = ["处理观演人弹窗"]

    def _verify_page_state(self, expected_step: str, all_steps: list, max_retries: int = 3) -> bool:
        """验证当前页面状态是否与预期步骤匹配。

        如果页面滞后，等待页面加载；如果页面超前，跳过中间步骤。
        """
        # 可选步骤不做页面验证，由步骤内部处理
        if expected_step in self.OPTIONAL_STEPS:
            logger.debug("可选步骤 '{}'，跳过页面验证", expected_step)
            return True

        for attempt in range(max_retries):
            current_page = self._detect_current_page()
            if not current_page or current_page == "未知":
                logger.debug("无法识别当前页面，继续执行")
                return True

            logger.debug("当前页面: {}, 预期步骤: {}", current_page, expected_step)

            # 检查页面是否匹配预期步骤
            if self._page_matches_step(current_page, expected_step):
                return True

            # 检查是否页面滞后（还在之前的步骤）
            step_names = [s[0] for s in all_steps]
            current_step_idx = self._current_step_index

            # 查找当前页面对应的步骤索引
            page_step_idx = self._find_step_for_page(current_page, step_names)

            if page_step_idx is not None and page_step_idx < current_step_idx:
                # 页面滞后，等待页面加载
                logger.warning("页面滞后: 当前在 '{}', 等待加载到 '{}'",
                             current_page, expected_step)
                time.sleep(1)
                continue
            elif page_step_idx is not None and page_step_idx > current_step_idx:
                # 页面超前，跳过中间步骤
                logger.info("页面已超前到 '{}'，跳过中间步骤", current_page)
                return True

            # 如果无法确定，继续执行
            return True

        logger.warning("页面状态验证超时，继续执行")
        return True

    def _detect_current_page(self) -> str | None:
        """使用 LLM 检测当前页面状态。"""
        if not (self.detector._llm and self.detector._llm.enabled):
            return None

        import json

        prompt = """分析以下 Android UI XML，判断当前页面处于抢票流程的哪个阶段。

可能的页面状态：
- 首页: 大麦首页，有搜索框、推荐内容
- 搜索页: 搜索输入页面，有输入框、历史记录
- 搜索结果: 搜索结果列表
- 演出详情: 演出详情页，显示演出信息、预定按钮
- 城市选择: 城市/观演地选择列表
- 观演人弹窗: 预选观演人的弹窗
- 场次选择: 选择演出场次
- 票档选择: 选择票价档位
- 数量选择: 选择购票数量
- 确认订单: 订单确认页面
- 支付页面: 支付/付款页面
- 未知: 无法识别

只输出 JSON:
{"page": "页面状态", "confidence": 0.0-1.0, "reason": "判断依据"}

XML (末尾是最上层):
"""
        try:
            xml_full = self.device.dump_hierarchy()
            # 取末尾部分（弹窗等覆盖层）+ 中间部分（主要内容）
            if len(xml_full) > 30000:
                xml = xml_full[-25000:]
            else:
                xml = xml_full

            response = self.detector._llm.chat(prompt + xml)
            if not response:
                return None

            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            result = json.loads(json_str)
            logger.debug("LLM 页面识别: {}", result)

            if result.get("confidence", 0) >= 0.6:
                return result.get("page", "未知")

        except Exception as e:
            logger.debug("LLM 页面识别失败: {}", e)

        return None

    def _page_matches_step(self, page: str, step: str) -> bool:
        """判断页面状态是否与步骤匹配。"""
        # 页面状态到可执行步骤的映射
        # 一个页面可能对应多个步骤（例如首页可以开始搜索）
        page_step_map = {
            "首页": ["启动应用", "搜索演出"],  # 首页可以直接开始搜索
            "搜索页": ["搜索演出"],
            "搜索结果": ["搜索演出", "选择城市"],
            "演出详情": ["选择城市", "处理观演人弹窗", "点击预定", "选择场次", "选择票档"],
            "城市选择": ["选择城市"],
            "观演人弹窗": ["处理观演人弹窗"],
            "场次选择": ["选择场次", "选择票档"],  # 场次和票档可能在同一页面
            "票档选择": ["选择票档", "选择张数"],  # 票档和张数可能在同一页面
            "数量选择": ["选择张数", "点击确定"],
            "确认订单": ["点击确定", "提交订单"],
            "支付页面": ["提交订单"],
        }

        valid_steps = page_step_map.get(page, [])
        return step in valid_steps or page == "未知"

    def _find_step_for_page(self, page: str, step_names: list) -> int | None:
        """查找页面对应的步骤索引。"""
        page_step_map = {
            "首页": "启动应用",
            "搜索页": "搜索演出",
            "搜索结果": "搜索演出",
            "演出详情": "点击预定",
            "城市选择": "选择城市",
            "观演人弹窗": "处理观演人弹窗",
            "场次选择": "选择场次",
            "票档选择": "选择票档",
            "数量选择": "选择张数",
            "确认订单": "点击确定",
            "支付页面": "提交订单",
        }

        step_name = page_step_map.get(page)
        if step_name and step_name in step_names:
            return step_names.index(step_name)
        return None

    # === 步骤实现 ===

    def _step_launch_app(self) -> bool:
        """步骤：确保大麦 App 正在运行。"""
        ensure_damai_running(self.device)
        time.sleep(2)  # 等待首页加载
        return True

    def _step_search_event(self) -> bool:
        """步骤：搜索目标演出。"""
        # 点击搜索区域
        search = self.detector.find(
            "search area",
            resourceId="cn.damai:id/homepage_header_search",
        )
        if not search:
            search = self.detector.find(
                "search button",
                resourceId="cn.damai:id/homepage_header_search_btn",
            )
        if not search:
            logger.error("找不到搜索入口")
            return False

        self.executor.click(search)
        time.sleep(0.5)

        # 输入关键词
        input_box = self.detector.find("search input", className="android.widget.EditText")
        if not input_box:
            logger.error("找不到搜索输入框")
            return False

        self.executor.input_text(input_box, self.config.keyword)
        logger.info("已输入关键词: {}", self.config.keyword)

        # 按回车搜索
        self.executor.press_key("enter")
        time.sleep(1.5)

        # 点击第一个搜索结果
        result = self.detector.find(
            "first search result",
            resourceId="cn.damai:id/tv_word",
            timeout=3.0,
        )
        if result:
            self.executor.click(result)
            time.sleep(1.5)
            return True

        # 备用方案：点击 RecyclerView 中第一项
        result = self.detector.find(
            "search result item",
            className="androidx.recyclerview.widget.RecyclerView",
            timeout=2.0,
        )
        if result:
            # 点击上方区域中心（第一个结果通常在此处）
            w, h = self.device.window_size()
            self.executor.tap(w // 2, h // 4)
            time.sleep(1.5)
            return True

        logger.error("未找到搜索结果")
        return False

    def _step_select_city(self) -> bool:
        """步骤：选择观演城市。"""
        if not self.config.city:
            logger.info("未配置城市，跳过城市选择")
            return True

        time.sleep(1)

        # 查找城市
        city = self.detector.find(
            f"city: {self.config.city}",
            textContains=self.config.city,
            timeout=3.0,
        )
        if city:
            self.executor.click(city)
            logger.info("已选择城市: {}", self.config.city)
            time.sleep(0.5)
            return True

        # 尝试滚动查找
        for _ in range(3):
            self.executor.swipe("left", scale=0.5)  # 城市列表可能是横向滚动
            time.sleep(0.3)
            city = self.detector.find(
                f"city: {self.config.city}",
                textContains=self.config.city,
                timeout=1.0,
            )
            if city:
                self.executor.click(city)
                logger.info("滑动后已选择城市: {}", self.config.city)
                time.sleep(0.5)
                return True

        # 使用 LLM 查找
        if self.detector._llm and self.detector._llm.enabled:
            result = self._llm_select_city()
            if result:
                return True

        logger.warning("未找到城市 '{}'，继续执行", self.config.city)
        return True

    def _llm_select_city(self) -> bool:
        """使用 LLM 智能选择城市。"""
        import json

        prompt = f"""分析以下 Android UI XML，找到城市/观演地选择列表。

任务：找到并定位城市 "{self.config.city}"。

城市选择特征：
- 通常是横向或纵向列表
- 显示城市名称，如 "北京"、"上海"、"长沙" 等
- 可能有 "全国" 或其他筛选选项

只输出 JSON:
{{"found": true/false, "strategy": "resourceId"|"text"|"textContains", "value": "定位值", "reason": "说明"}}

XML:
"""
        try:
            xml_full = self.device.dump_hierarchy()
            xml = xml_full[:30000] if len(xml_full) > 30000 else xml_full

            response = self.detector._llm.chat(prompt + xml)
            if not response:
                return False

            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            result = json.loads(json_str)
            logger.debug("LLM 城市选择: {}", result)

            if not result.get("found", False):
                return False

            strategy = result.get("strategy", "")
            value = result.get("value", "")

            if strategy and value:
                selector = {strategy: value}
                element = self.device(**selector)
                if element.exists(timeout=2.0):
                    element.click()
                    logger.info("LLM 已选择城市: {} ({})", self.config.city, selector)
                    time.sleep(0.5)
                    return True

        except Exception as e:
            logger.debug("LLM 城市选择失败: {}", e)

        return False

    def _step_handle_viewer_popup(self) -> bool:
        """步骤：处理预填观演人弹窗（可选步骤）。

        弹窗有两个选项：
        1. 预选实名观演人 - 选择观演人后点击确定
        2. 知道了 - 跳过预选

        注意：不是所有演出都有此弹窗，没有弹窗时直接跳过。
        """
        # 快速检查是否有弹窗（短超时）
        popup_title = self.detector.find(
            "viewer popup",
            textContains="观演人",
            timeout=1.5,
        )

        if not popup_title:
            # 再检查 "知道了" 按钮（弹窗可能只有这个按钮）
            know_btn = self.detector.find(
                "know button",
                text="知道了",
                timeout=0.5,
            )
            if know_btn:
                self.executor.click(know_btn)
                logger.info("点击知道了，跳过观演人弹窗")
                time.sleep(0.3)
                return True
            # 没有弹窗，直接跳过此步骤
            logger.info("未检测到观演人弹窗，跳过此步骤")
            return True

        # 如果配置了购票人，尝试预选
        if self.config.users:
            # 点击 "预选实名观演人" 按钮
            preselect_btn = self.detector.find(
                "preselect button",
                textContains="预选",
                timeout=2.0,
            )
            if preselect_btn:
                self.executor.click(preselect_btn)
                logger.info("点击预选实名观演人")
                time.sleep(0.5)

                # 选择配置的观演人
                selected = 0
                for user_name in self.config.users:
                    user_el = self.detector.find(
                        f"viewer: {user_name}",
                        textContains=user_name,
                        timeout=2.0,
                    )
                    if user_el:
                        self.executor.click(user_el)
                        logger.info("已选择观演人: {}", user_name)
                        selected += 1
                        time.sleep(0.2)
                    else:
                        logger.warning("未找到观演人: {}", user_name)

                # 点击确定
                if selected > 0:
                    confirm = self.detector.find(
                        "confirm viewer",
                        text="确定",
                        timeout=2.0,
                    )
                    if confirm:
                        self.executor.click(confirm)
                        logger.info("确认观演人选择")
                        time.sleep(0.5)
                        return True

        # 回退：点击 "知道了" 跳过
        skip_btn = self.detector.find(
            "skip viewer popup",
            text="知道了",
            timeout=2.0,
        )
        if skip_btn:
            self.executor.click(skip_btn)
            logger.info("跳过观演人预选")
            time.sleep(0.5)
            return True

        # 尝试 LLM 处理
        if self.detector._llm and self.detector._llm.enabled:
            logger.info("使用 LLM 处理观演人弹窗")
            # 弹窗监听会处理
            time.sleep(2)
            return True

        logger.warning("观演人弹窗处理失败，继续执行")
        return True

    def _step_select_session(self) -> bool:
        """步骤：选择场次（显示有票/预售的场次）。"""
        time.sleep(1)

        # 使用 LLM 智能选择场次
        if self.detector._llm and self.detector._llm.enabled:
            result = self._llm_select_session()
            if result:
                return True

        # 回退方案：查找包含 "有票" 或 "预售" 的场次
        for status_text in ["有票", "预售"]:
            session = self.detector.find(
                f"available session ({status_text})",
                textContains=status_text,
                timeout=2.0,
            )
            if session:
                # 如果配置了场次关键词，检查是否匹配
                if self.config.session:
                    # 需要找到同时包含状态和场次关键词的
                    session = self.detector.find(
                        f"session: {self.config.session}",
                        textContains=self.config.session,
                        timeout=1.0,
                    )
                    if session:
                        self.executor.click(session)
                        logger.info("已选择场次: {}", self.config.session)
                        time.sleep(0.5)
                        return True
                else:
                    # 点击找到的有票场次
                    self.executor.click(session)
                    logger.info("已选择可购买场次 ({})", status_text)
                    time.sleep(0.5)
                    return True

        logger.warning("未找到可购买场次，继续执行")
        return True

    def _llm_select_session(self) -> bool:
        """使用 LLM 智能选择场次。"""
        import json

        prompt = f"""分析以下 Android UI XML，找到演唱会/演出的场次列表。

任务：找到一个可以购买的场次（显示"有票"或"预售"状态的）。
{f'优先选择包含 "{self.config.session}" 的场次。' if self.config.session else '选择第一个可购买的场次。'}

场次特征：
- 通常显示日期时间信息（如 "03月15日 周六 20:00"）
- 旁边有状态标签："有票"、"预售"、"即将开售"、"已售罄"
- 只有 "有票" 和 "预售" 状态的才能购买

只输出 JSON:
{{"found": true/false, "strategy": "resourceId"|"text"|"textContains", "value": "定位值", "session_info": "场次描述", "reason": "说明"}}

XML:
"""
        try:
            xml_full = self.device.dump_hierarchy()
            # 场次通常在页面中部
            xml = xml_full[:40000] if len(xml_full) > 40000 else xml_full

            response = self.detector._llm.chat(prompt + xml)
            if not response:
                return False

            # 提取 JSON
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            result = json.loads(json_str)
            logger.debug("LLM 场次选择: {}", result)

            if not result.get("found", False):
                logger.warning("LLM 未找到可购买场次: {}", result.get("reason", ""))
                return False

            strategy = result.get("strategy", "")
            value = result.get("value", "")
            session_info = result.get("session_info", "")

            if strategy and value:
                selector = {strategy: value}
                element = self.device(**selector)
                if element.exists(timeout=2.0):
                    element.click()
                    logger.info("LLM 已选择场次: {} ({})", session_info, selector)
                    time.sleep(0.5)
                    return True

        except Exception as e:
            logger.debug("LLM 场次选择失败: {}", e)

        return False

    def _step_click_buy(self) -> bool:
        """步骤：点击购买按钮。"""
        time.sleep(1)

        # 尝试已知按钮 ID
        buy_ids = [
            "cn.damai:id/trade_project_detail_purchase_status_bar_container_fl",
            "cn.damai:id/btn_buy",
        ]
        for rid in buy_ids:
            btn = self.detector.find(f"buy button ({rid})", resourceId=rid, timeout=2.0)
            if btn:
                self.executor.click(btn)
                logger.info("已点击购买按钮")
                time.sleep(1)
                return True

        # 尝试文本匹配
        buy_texts = ["立即购买", "选座购买", "立即预约", "购买"]
        for text in buy_texts:
            btn = self.detector.find(f"buy: {text}", textContains=text, timeout=1.0)
            if btn:
                self.executor.click(btn)
                logger.info("已点击购买按钮: {}", text)
                time.sleep(1)
                return True

        # 最后手段：点击底部中心（购买按钮通常在底部）
        w, h = self.device.window_size()
        self.executor.tap(w // 2, int(h * 0.95))
        logger.warning("Tapped bottom center as buy button fallback")
        time.sleep(1)
        return True

    def _step_select_price(self) -> bool:
        """步骤：选择票档。

        票档规则：
        - 只显示金额 = 可购买
        - 显示"缺货登记" = 不可购买
        """
        time.sleep(0.5)

        # 优先使用 LLM 智能选择
        if self.detector._llm and self.detector._llm.enabled:
            result = self._llm_select_price()
            if result:
                return True

        # 回退方案：避开"缺货登记"的票档
        # 查找所有票档元素，排除包含"缺货"的
        unavailable = self.detector.find(
            "unavailable price",
            textContains="缺货",
            timeout=1.0,
        )

        # 尝试点击第一个可见的价格（纯数字/金额）
        price_patterns = ["¥", "元", "价"]
        for pattern in price_patterns:
            price = self.detector.find(
                f"price with {pattern}",
                textContains=pattern,
                timeout=1.0,
            )
            if price:
                self.executor.click(price)
                logger.info("已选择票档")
                time.sleep(0.3)
                return True

        logger.warning("票档选择失败，继续执行")
        return True

    def _llm_select_price(self) -> bool:
        """使用 LLM 智能选择可购买的票档。"""
        import json

        prompt = f"""分析以下 Android UI XML，找到票档/价格选择列表。

任务：找到一个可以购买的票档。
{'优先选择第 ' + str(self.config.price_index + 1) + ' 个票档（如果可购买）。' if self.config.price_index > 0 else '选择第一个可购买的票档。'}

票档规则：
- 只显示金额（如 "¥680"、"680元"）= 可购买
- 显示 "缺货登记"、"缺货"、"售罄"、"暂无" = 不可购买
- 显示 "预售"、"有票" = 可购买

请找到可购买的票档，返回定位信息。

只输出 JSON:
{{"found": true/false, "strategy": "resourceId"|"text"|"textContains", "value": "定位值", "price_info": "票档描述如¥680", "reason": "说明"}}

XML:
"""
        try:
            xml_full = self.device.dump_hierarchy()
            xml = xml_full[:35000] if len(xml_full) > 35000 else xml_full

            response = self.detector._llm.chat(prompt + xml)
            if not response:
                return False

            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            result = json.loads(json_str)
            logger.debug("LLM 票档选择: {}", result)

            if not result.get("found", False):
                logger.warning("LLM 未找到可购买票档: {}", result.get("reason", ""))
                return False

            strategy = result.get("strategy", "")
            value = result.get("value", "")
            price_info = result.get("price_info", "")

            if strategy and value:
                selector = {strategy: value}
                element = self.device(**selector)
                if element.exists(timeout=2.0):
                    element.click()
                    logger.info("LLM 已选择票档: {} ({})", price_info, selector)
                    time.sleep(0.3)
                    return True

        except Exception as e:
            logger.debug("LLM 票档选择失败: {}", e)

        return False

    def _step_select_quantity(self) -> bool:
        """Step: adjust ticket quantity."""
        quantity_needed = len(self.config.users)
        if quantity_needed <= 1:
            logger.info("Single ticket, skipping quantity adjustment")
            return True

        # Find the + button
        plus = self.detector.find("plus button", resourceId="img_jia", timeout=2.0)
        if not plus:
            plus = self.detector.find("plus button alt", description="增加", timeout=1.0)

        if plus:
            clicks = quantity_needed - 1
            for _ in range(clicks):
                self.executor.click(plus)
                time.sleep(0.05)
            logger.info("Set quantity to {}", quantity_needed)
        else:
            logger.warning("Quantity button not found, continuing")

        return True

    def _step_confirm_purchase(self) -> bool:
        """Step: confirm purchase (intermediate confirmation)."""
        # Try known confirm button
        confirm = self.detector.find("confirm button", resourceId="btn_buy_view", timeout=2.0)
        if confirm:
            self.executor.click(confirm)
            logger.info("Clicked confirm button")
            time.sleep(0.8)
            return True

        # Try text
        for text in ["确定", "确认", "立即购买"]:
            confirm = self.detector.find(f"confirm: {text}", text=text, timeout=1.0)
            if confirm:
                self.executor.click(confirm)
                logger.info("Clicked confirm: {}", text)
                time.sleep(0.8)
                return True

        logger.warning("No confirm button found, page may have auto-advanced")
        return True

    def _step_submit_order(self) -> bool:
        """Step: submit the final order."""
        if not self.config.if_commit_order:
            logger.info("Order submission disabled in config")
            return True

        submit = self.detector.find("submit button", text="立即提交", timeout=3.0)
        if submit:
            self.executor.click(submit)
            logger.info("Order submitted!")
            return True

        # Fallback texts
        for text in ["提交订单", "立即支付", "确认订单"]:
            submit = self.detector.find(f"submit: {text}", textContains=text, timeout=1.0)
            if submit:
                self.executor.click(submit)
                logger.info("Order submitted via: {}", text)
                return True

        logger.error("Submit button not found")
        return False
