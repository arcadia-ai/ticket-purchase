"""Core ticket grabbing workflow orchestration."""
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
    """Ticket purchase configuration loaded from YAML."""
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
        # Filter to known fields, warn about unknown keys
        known = set(TicketConfig.__dataclass_fields__)
        unknown = set(data) - known
        if unknown:
            logger.warning("Unknown config keys ignored: {}", unknown)
        return TicketConfig(**{k: v for k, v in data.items() if k in known})


class TicketWorkflow:
    """Orchestrates the complete ticket grabbing process."""

    def __init__(self, device, config: TicketConfig):
        self.device = device
        self.config = config
        self.detector = Detector(device)
        self.executor = Executor(device)
        self.recovery = RecoveryManager(device)

    def run(self) -> bool:
        """Execute the full ticket grabbing flow.

        Returns True if order submitted successfully.
        """
        logger.info("=" * 50)
        logger.info("Starting ticket grabbing flow")
        logger.info("Keyword: {}, City: {}, Users: {}",
                    self.config.keyword, self.config.city, self.config.users)
        logger.info("=" * 50)

        start_time = time.time()
        self.recovery.start_popup_watcher()

        try:
            steps = [
                ("Launch app", self._step_launch_app),
                ("Search event", self._step_search_event),
                ("Select city/date", self._step_select_city_date),
                ("Click buy", self._step_click_buy),
                ("Select price", self._step_select_price),
                ("Select quantity", self._step_select_quantity),
                ("Confirm purchase", self._step_confirm_purchase),
                ("Select users", self._step_select_users),
                ("Submit order", self._step_submit_order),
            ]

            for step_name, step_func in steps:
                logger.info("--- {} ---", step_name)
                success = self.recovery.retry_step(step_func, step_name)
                if not success:
                    logger.error("Failed at step: {}", step_name)
                    take_screenshot(self.device, f"fail_{step_name.replace(' ', '_')}")
                    return False
                take_screenshot(self.device, f"step_{step_name.replace(' ', '_')}")

            elapsed = time.time() - start_time
            logger.info("=" * 50)
            logger.info("Flow completed in {:.1f}s", elapsed)
            logger.info("=" * 50)
            return True

        except Exception as e:
            logger.error("Unexpected error: {}", e)
            take_screenshot(self.device, "exception")
            return False
        finally:
            self.recovery.stop_popup_watcher()

    def run_with_retry(self) -> bool:
        """Run the flow with overall retry logic."""
        for attempt in range(1, self.config.max_retry + 1):
            logger.info("Attempt {}/{}", attempt, self.config.max_retry)
            if self.run():
                logger.info("Ticket grabbing succeeded!")
                return True

            if attempt < self.config.max_retry:
                logger.info("Retrying in 2s...")
                time.sleep(2)
                # Press back to reset state
                self.recovery.press_back_to_recover()

        logger.error("All {} attempts failed", self.config.max_retry)
        return False

    # === Step implementations ===

    def _step_launch_app(self) -> bool:
        """Step: ensure Damai app is running."""
        ensure_damai_running(self.device)
        time.sleep(2)  # Wait for homepage
        return True

    def _step_search_event(self) -> bool:
        """Step: search for the target event."""
        # Click search area
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
            logger.error("Cannot find search entry")
            return False

        self.executor.click(search)
        time.sleep(0.5)

        # Input keyword
        input_box = self.detector.find("search input", className="android.widget.EditText")
        if not input_box:
            logger.error("Cannot find search input")
            return False

        self.executor.input_text(input_box, self.config.keyword)
        logger.info("Entered keyword: {}", self.config.keyword)

        # Press Enter to search
        self.executor.press_key("enter")
        time.sleep(1.5)

        # Click first search result
        result = self.detector.find(
            "first search result",
            resourceId="cn.damai:id/tv_word",
            timeout=3.0,
        )
        if result:
            self.executor.click(result)
            time.sleep(1.5)
            return True

        # Fallback: click first item in RecyclerView
        result = self.detector.find(
            "search result item",
            className="androidx.recyclerview.widget.RecyclerView",
            timeout=2.0,
        )
        if result:
            # Tap center of upper area (where first result usually is)
            w, h = self.device.window_size()
            self.executor.tap(w // 2, h // 4)
            time.sleep(1.5)
            return True

        logger.error("No search results found")
        return False

    def _step_select_city_date(self) -> bool:
        """Step: select city and date."""
        # Select city
        if self.config.city:
            city = self.detector.find(
                f"city: {self.config.city}",
                textContains=self.config.city,
                timeout=3.0,
            )
            if city:
                self.executor.click(city)
                logger.info("Selected city: {}", self.config.city)
                time.sleep(0.5)
            else:
                # Try scrolling to find city
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
                        logger.info("Selected city after scroll: {}", self.config.city)
                        time.sleep(0.5)
                        break
                else:
                    logger.warning("City '{}' not found, continuing", self.config.city)

        # Select date (optional)
        if self.config.date:
            date_el = self.detector.find(
                f"date: {self.config.date}",
                textContains=self.config.date,
                timeout=2.0,
            )
            if date_el:
                self.executor.click(date_el)
                logger.info("Selected date: {}", self.config.date)
                time.sleep(0.5)
            else:
                logger.warning("Date '{}' not found, skipping", self.config.date)

        return True

    def _step_click_buy(self) -> bool:
        """Step: click the buy/purchase button."""
        time.sleep(1)

        # Try known button IDs
        buy_ids = [
            "cn.damai:id/trade_project_detail_purchase_status_bar_container_fl",
            "cn.damai:id/btn_buy",
        ]
        for rid in buy_ids:
            btn = self.detector.find(f"buy button ({rid})", resourceId=rid, timeout=2.0)
            if btn:
                self.executor.click(btn)
                logger.info("Clicked buy button")
                time.sleep(1)
                return True

        # Try text matching
        buy_texts = ["立即购买", "选座购买", "立即预约", "购买"]
        for text in buy_texts:
            btn = self.detector.find(f"buy: {text}", textContains=text, timeout=1.0)
            if btn:
                self.executor.click(btn)
                logger.info("Clicked buy button: {}", text)
                time.sleep(1)
                return True

        # Last resort: tap bottom center (buy button is usually at bottom)
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
