"""核心抢票工作流编排。"""
import json
import time
from dataclasses import dataclass, field

import yaml
from loguru import logger

from .detector import Detector
from .executor import Executor
from .log import take_screenshot
from .monitor import ensure_damai_running, wait_for_element
from .recovery import RecoveryManager


# LLM 自主代理的系统提示
AUTONOMOUS_AGENT_PROMPT = """你是大麦 App 抢票助手，负责自动完成购票流程。

## 购票流程（必须按顺序执行）
1. 启动大麦 App（进入首页）
2. 点击搜索框，输入关键词，点击搜索或回车
3. 在搜索结果中点击目标演出
4. **重要：点击城市/观演地（如"长沙"、"北京"等）进入该城市的演出详情页**
5. 处理弹窗（如有"预选观演人"弹窗，点"知道了"跳过）
6. **点击购买按钮（可能显示为：立即预定、立即购买、立即预约、选座购买、购票）**
7. 选择场次（选择显示"有票"或"预售"的场次，点击场次日期区域）
8. 选择票档（选择显示价格的，避开"缺货登记"）
9. 选择数量（如需多张，点击"+"按钮）
10. 点击"确定"按钮
11. 点击"提交订单"或"立即支付"

## 关键说明
- 搜索结果页会显示多个城市的场次，必须点击目标城市才能进入详情页
- "立即预定" = "立即购买" = "立即预约" = "选座购买" = 购买按钮，都要点击
- 场次选择时，"有票"/"预售"表示可购买，"售罄"/"缺货"表示不可购买
- 票档选择时，只有价格（如"¥680"）的可以选，有"缺货登记"的不能选

## 购票配置
- 关键词: {keyword}
- 城市: {city}
- 场次偏好: {session}
- 观演人: {users}
- 票档索引: {price_index}
- 是否提交: {if_commit_order}

## 你的任务
分析当前页面 XML，判断当前处于哪个步骤，然后决定下一步操作。

## 操作类型
- click: 点击元素（提供定位方式）
- tap: 点击坐标（提供 x, y）
- input: 输入文本（提供元素定位和文本）
- key: 按键（如 enter 回车、back 返回）
- swipe: 滑动（提供方向 up/down/left/right）
- wait: 等待页面加载（提供秒数）
- done: 流程完成
- failed: 流程失败（说明原因）

## 常用技巧
- 输入关键词后，如果没有搜索按钮，直接按回车（key: enter）进入搜索结果
- 如果页面卡住，可以按返回键（key: back）重试

## 输出格式（只输出 JSON）
{{
    "current_step": "当前处于的步骤",
    "page_analysis": "页面分析（简短）",
    "action": "click|tap|input|key|swipe|wait|done|failed",
    "selector": {{"strategy": "resourceId|text|textContains|className", "value": "从XML中复制的实际值"}},
    "tap_position": {{"x": 0, "y": 0}},
    "input_text": "要输入的文本",
    "key_name": "enter|back|home",
    "swipe_direction": "up|down|left|right",
    "wait_seconds": 1,
    "reason": "操作原因"
}}

## 如何从 XML 找元素
1. **XML 开头是页面主要内容**（搜索结果、演出列表等），**末尾是弹窗层**
2. 搜索结果/演出列表: 通常在 XML 开头部分，找 text 包含演出名称、城市名的节点
3. 搜索框: 找 resource-id 包含 "search" 的节点
4. 按钮: 找 text="xxx" 的节点，使用 text 或 textContains 策略
5. 输入框: 找 class="android.widget.EditText" 的节点
6. 示例: <node resource-id="cn.damai:id/xxx" text="搜索" /> -> 用 resourceId="cn.damai:id/xxx" 或 text="搜索"

**重要：搜索结果在 XML 开头，不要只看末尾部分！**

## 已知元素参考（优先使用这些）
- 首页搜索框（点击进入搜索）:
  - resourceId="cn.damai:id/homepage_header_search"
  - 或 textContains="搜索"
  - 或 textContains="搜你想看"
- 搜索输入框（输入关键词）: className="android.widget.EditText"
- 购买按钮（任意一个都是购买入口）:
  - textContains="立即预定"
  - textContains="立即购买"
  - textContains="立即预约"
  - textContains="选座购买"
  - textContains="购票"
- 确定按钮: text="确定" 或 textContains="确认"
- 提交按钮: textContains="提交" 或 textContains="支付"
- 关闭弹窗: text="知道了" 或 text="我知道了" 或 text="跳过"
- 城市/观演地: textContains="目标城市名"（在搜索结果页点击城市进入详情）

## 注意事项
- 从 XML 中找到实际存在的元素，不要猜测 resourceId
- 如果 resourceId 不确定，优先使用 text 或 textContains 定位
- **"立即预定"就是购买按钮**，看到就点击它
- **搜索结果页必须先点击城市名（如"长沙"）才能进入详情页**
- 状态标签（如"预售"、"有票"）不可点击，要点击其左侧的场次日期
- 弹窗覆盖层在 XML 末尾，优先处理弹窗
- 如果元素不可见，尝试滑动（swipe up/down）查找
- 如果同一操作失败 3 次，尝试其他方式或返回 failed
- 仔细查看 XML 中的 text 属性，找到对应的按钮

当前页面 XML:
"""


class AutonomousWorkflow:
    """LLM 自主控制的抢票流程。"""

    def __init__(self, device, config: "TicketConfig"):
        self.device = device
        self.config = config
        self.detector = Detector(device)
        self.executor = Executor(device)
        self.recovery = RecoveryManager(device, llm_client=self.detector._llm)
        self._step_count = 0
        self._max_steps = 50  # 防止死循环
        self._stuck_count = 0
        self._last_action = None

    def run(self) -> bool:
        """执行自主抢票流程。"""
        if not (self.detector._llm and self.detector._llm.enabled):
            logger.error("自主模式需要启用 LLM")
            return False

        logger.info("=" * 50)
        logger.info("自主模式启动")
        logger.info("关键词: {}, 城市: {}, 观演人: {}",
                    self.config.keyword, self.config.city or "自动", self.config.users)
        logger.info("=" * 50)

        # 启动 App
        ensure_damai_running(self.device)
        time.sleep(2)

        start_time = time.time()

        while self._step_count < self._max_steps:
            self._step_count += 1
            logger.info("--- 步骤 {} ---", self._step_count)

            # 获取 LLM 决策
            decision = self._get_llm_decision()
            if not decision:
                logger.error("LLM 决策失败")
                self._stuck_count += 1
                if self._stuck_count >= 3:
                    logger.error("连续失败 3 次，终止流程")
                    return False
                time.sleep(1)
                continue

            self._stuck_count = 0
            action = decision.get("action", "")
            current_step = decision.get("current_step", "未知")
            reason = decision.get("reason", "")

            logger.info("当前步骤: {} | 操作: {} | 原因: {}", current_step, action, reason)

            # 执行操作
            if action == "done":
                elapsed = time.time() - start_time
                logger.info("=" * 50)
                logger.info("流程完成！耗时 {:.1f}秒", elapsed)
                logger.info("=" * 50)
                take_screenshot(self.device, "autonomous_done")
                return True

            elif action == "failed":
                logger.error("流程失败: {}", reason)
                take_screenshot(self.device, "autonomous_failed")
                return False

            elif action == "click":
                self._execute_click(decision)

            elif action == "tap":
                self._execute_tap(decision)

            elif action == "input":
                self._execute_input(decision)

            elif action == "swipe":
                self._execute_swipe(decision)

            elif action == "key":
                self._execute_key(decision)

            elif action == "wait":
                wait_time = decision.get("wait_seconds", 1)
                logger.debug("等待 {}秒", wait_time)
                time.sleep(wait_time)

            else:
                logger.warning("未知操作: {}", action)

            # 检测重复操作（可能卡住了）
            current_action = f"{action}:{decision.get('selector', decision.get('tap_position', ''))}"
            if current_action == self._last_action:
                self._stuck_count += 1
                if self._stuck_count >= 3:
                    logger.warning("重复操作 3 次，尝试其他方式")
            else:
                self._stuck_count = 0
            self._last_action = current_action

            # 截图（每 5 步或关键步骤）
            if self._step_count % 5 == 0 or action in ["click", "input"]:
                take_screenshot(self.device, f"auto_step_{self._step_count}")

            time.sleep(0.3)

        logger.error("超过最大步骤数 {}，终止流程", self._max_steps)
        return False

    def _get_llm_decision(self) -> dict | None:
        """获取 LLM 的下一步决策。"""
        try:
            # 获取页面 XML
            xml_full = self.device.dump_hierarchy()
            xml_len = len(xml_full)

            # 智能截取：优先保留包含关键元素的部分
            if xml_len <= 60000:
                # 60KB 以内直接用完整 XML
                xml = xml_full
            else:
                # 超长 XML：取开头 25000 + 末尾 25000
                xml = xml_full[:25000] + "\n\n...[中间省略]...\n\n" + xml_full[-25000:]
                logger.debug("XML 截取: 总长={}, 取开头+末尾各25000", xml_len)

            # 构建 prompt
            prompt = AUTONOMOUS_AGENT_PROMPT.format(
                keyword=self.config.keyword,
                city=self.config.city or "不限",
                session=self.config.session or "第一个可购买",
                users=", ".join(self.config.users) if self.config.users else "未指定",
                price_index=self.config.price_index,
                if_commit_order="是" if self.config.if_commit_order else "否（仅测试）",
            ) + xml

            response = self.detector._llm.chat(prompt)
            if not response:
                return None

            # 提取 JSON
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            result = json.loads(json_str)
            logger.debug("LLM 决策: {}", result)
            return result

        except Exception as e:
            logger.error("LLM 决策解析失败: {}", e)
            return None

    def _execute_click(self, decision: dict):
        """执行点击操作。"""
        selector = decision.get("selector", {})
        strategy = selector.get("strategy", "")
        value = selector.get("value", "")

        if not strategy or not value:
            logger.warning("点击缺少选择器信息")
            return False

        element = self.device(**{strategy: value})
        if element.exists(timeout=2.0):
            element.click()
            logger.debug("点击成功: {}={}", strategy, value)
            time.sleep(0.3)
            return True

        logger.warning("元素不存在: {}={}", strategy, value)

        # 尝试备选策略
        fallback_strategies = []
        if strategy == "resourceId":
            # resourceId 失败，尝试用 textContains
            if "search" in value.lower():
                fallback_strategies.append({"textContains": "搜索"})
                fallback_strategies.append({"resourceId": "cn.damai:id/homepage_header_search"})
            elif "buy" in value.lower():
                fallback_strategies.append({"textContains": "购买"})
                fallback_strategies.append({"textContains": "预定"})

        for fallback in fallback_strategies:
            logger.debug("尝试备选: {}", fallback)
            element = self.device(**fallback)
            if element.exists(timeout=1.0):
                element.click()
                logger.info("备选点击成功: {}", fallback)
                time.sleep(0.3)
                return True

        return False

    def _execute_tap(self, decision: dict):
        """执行坐标点击。"""
        pos = decision.get("tap_position", {})
        x = pos.get("x", 0)
        y = pos.get("y", 0)

        if x and y:
            self.executor.tap(x, y)
            logger.debug("点击坐标: ({}, {})", x, y)
            time.sleep(0.3)

    def _execute_input(self, decision: dict):
        """执行输入操作。"""
        selector = decision.get("selector", {})
        strategy = selector.get("strategy", "")
        value = selector.get("value", "")
        text = decision.get("input_text", "")

        if not text:
            logger.warning("输入缺少文本")
            return

        if strategy and value:
            element = self.device(**{strategy: value})
            if element.exists(timeout=2.0):
                element.set_text(text)
                logger.debug("输入: {} -> {}", value, text)
        else:
            # 直接输入（可能已经聚焦）
            self.device.send_keys(text)
            logger.debug("直接输入: {}", text)

        time.sleep(0.2)

    def _execute_swipe(self, decision: dict):
        """执行滑动操作。"""
        direction = decision.get("swipe_direction", "up")
        self.executor.swipe(direction, scale=0.5)
        logger.debug("滑动: {}", direction)
        time.sleep(0.5)

    def _execute_key(self, decision: dict):
        """执行按键操作。"""
        key_name = decision.get("key_name", "")
        if not key_name:
            logger.warning("按键缺少 key_name")
            return

        self.device.press(key_name)
        logger.debug("按键: {}", key_name)
        time.sleep(0.3)


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
                # 获取元素位置，点击其左侧区域（场次信息通常在状态标签左边）
                try:
                    bounds = session.info.get("bounds", {})
                    if bounds:
                        # 点击状态标签左侧 200 像素处（场次条目区域）
                        x = max(bounds.get("left", 0) - 200, 100)
                        y = (bounds.get("top", 0) + bounds.get("bottom", 0)) // 2
                        logger.debug("场次状态位置: {}, 点击偏移位置: ({}, {})", bounds, x, y)
                        self.executor.tap(x, y)
                        logger.info("已选择可购买场次 ({})", status_text)
                        time.sleep(0.5)
                        return True
                except Exception as e:
                    logger.debug("获取场次位置失败: {}", e)
                    # 尝试直接点击
                    self.executor.click(session)
                    logger.info("已点击场次状态 ({})", status_text)
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

重要：返回场次条目的**可点击区域**，不是状态标签本身！
- 优先返回场次的日期/时间文本（如 "03月15日"）
- 或者返回场次条目的父容器 resourceId
- 不要返回 "有票"、"预售" 等状态标签

只输出 JSON:
{{"found": true/false, "strategy": "resourceId"|"text"|"textContains", "value": "场次日期或容器ID，不是状态标签", "session_info": "场次描述", "reason": "说明"}}

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
