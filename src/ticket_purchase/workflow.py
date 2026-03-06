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
    keyword: str
    city: str = ""
    date: str = ""
    price_index: int = 0
    users: list = field(default_factory=lambda: [])
    target_time: str = ""
    if_commit_order: bool = True
    max_retry: int = 3

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

    def __init__(self, device, config: TicketConfig):
        self.device = device
        self.config = config
        self.detector = Detector(device)
        self.executor = Executor(device)
        # 共享 LLM client 给 recovery 模块
        self.recovery = RecoveryManager(device, llm_client=self.detector._llm)

    def run(self) -> bool:
        """执行完整的抢票流程。

        订单提交成功返回 True。
        """
        logger.info("=" * 50)
        logger.info("开始执行抢票流程")
        logger.info("关键词: {}, 城市: {}, 购票人: {}",
                    self.config.keyword, self.config.city, self.config.users)
        logger.info("=" * 50)

        start_time = time.time()
        self.recovery.start_popup_watcher()

        try:
            steps = [
                ("启动应用", self._step_launch_app),
                ("搜索演出", self._step_search_event),
                ("选择城市/日期", self._step_select_city_date),
                ("点击购买", self._step_click_buy),
                ("选择票价", self._step_select_price),
                ("选择数量", self._step_select_quantity),
                ("确认购买", self._step_confirm_purchase),
                ("选择购票人", self._step_select_users),
                ("提交订单", self._step_submit_order),
            ]

            for step_name, step_func in steps:
                logger.info("--- {} ---", step_name)
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

    def _step_select_city_date(self) -> bool:
        """步骤：选择城市和日期。"""
        # 选择城市
        if self.config.city:
            city = self.detector.find(
                f"city: {self.config.city}",
                textContains=self.config.city,
                timeout=3.0,
            )
            if city:
                self.executor.click(city)
                logger.info("已选择城市: {}", self.config.city)
                time.sleep(0.5)
            else:
                # 尝试滚动查找城市
                for _ in range(2):
                    self.executor.swipe("up", scale=0.5)
                    time.sleep(0.3)
                    city = self.detector.find(
                        f"city: {self.config.city}",
                        textContains=self.config.city,
                        timeout=1.0,
                    )
                    if city:
                        self.executor.click(city)
                        logger.info("滚动后已选择城市: {}", self.config.city)
                        time.sleep(0.5)
                        break
                else:
                    logger.warning("未找到城市 '{}'，继续执行", self.config.city)

        # 选择日期（可选）
        if self.config.date:
            date_el = self.detector.find(
                f"date: {self.config.date}",
                textContains=self.config.date,
                timeout=2.0,
            )
            if date_el:
                self.executor.click(date_el)
                logger.info("已选择日期: {}", self.config.date)
                time.sleep(0.5)
            else:
                logger.warning("未找到日期 '{}'，跳过", self.config.date)

        return True

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
        """Step: select ticket price tier."""
        price_container = self.detector.find(
            "price container",
            resourceId="cn.damai:id/project_detail_perform_price_flowlayout",
            timeout=3.0,
        )
        if not price_container:
            logger.warning("Price container not found, may already be selected")
            return True

        time.sleep(0.3)

        # Find price options by FrameLayout children
        prices = self.detector.find_all(
            "price options",
            resourceId="cn.damai:id/project_detail_perform_price_flowlayout",
        )
        # Use index-based selection within the container
        # u2 doesn't easily support child indexing, so use XPath
        try:
            xpath = f'//android.widget.FrameLayout[@resource-id="cn.damai:id/project_detail_perform_price_flowlayout"]/android.widget.FrameLayout[{self.config.price_index + 1}]'
            target = self.device.xpath(xpath)
            if target.exists:
                target.click()
                logger.info("Selected price index: {}", self.config.price_index)
                time.sleep(0.3)
                return True
        except Exception as e:
            logger.debug("XPath price selection failed: {}", e)

        logger.warning("Price selection failed, continuing anyway")
        return True

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

    def _step_select_users(self) -> bool:
        """Step: select ticket purchasers."""
        if not self.config.users:
            logger.warning("No users configured")
            return True

        selected = 0
        for user_name in self.config.users:
            user_el = self.detector.find(
                f"user: {user_name}",
                textContains=user_name,
                timeout=2.0,
            )
            if user_el:
                self.executor.click(user_el)
                logger.info("Selected user: {}", user_name)
                selected += 1
                time.sleep(0.1)
            else:
                logger.error("User not found: {}", user_name)

        return selected > 0

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
