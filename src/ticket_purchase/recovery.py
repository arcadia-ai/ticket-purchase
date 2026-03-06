"""Error recovery: popup dismissal, step retry, page navigation."""
import threading
import time

import uiautomator2 as u2
from loguru import logger

# Common popup dismiss button patterns
POPUP_DISMISS_PATTERNS = [
    {"text": "我知道了"},
    {"text": "知道了"},
    {"text": "关闭"},
    {"text": "取消"},
    {"text": "暂不"},
    {"text": "跳过"},
    {"text": "不再提醒"},
    {"textContains": "同意"},
    {"resourceId": "cn.damai:id/btn_close"},
    {"resourceId": "cn.damai:id/iv_close"},
    {"description": "关闭"},
]

DAMAI_PACKAGE = "cn.damai"


class RecoveryManager:
    """Manages error recovery and popup dismissal."""

    def __init__(self, device: u2.Device):
        self.device = device
        self._popup_thread = None
        self._stop_event = threading.Event()

    def start_popup_watcher(self, interval: float = 1.5):
        """Start background thread that auto-dismisses popups."""
        if self._popup_thread and self._popup_thread.is_alive():
            return

        self._stop_event.clear()
        self._popup_thread = threading.Thread(
            target=self._popup_watch_loop,
            args=(interval,),
            daemon=True,
        )
        self._popup_thread.start()
        logger.info("Popup watcher started (interval={}s)", interval)

    def stop_popup_watcher(self):
        """Stop the popup watcher thread."""
        self._stop_event.set()
        if self._popup_thread:
            self._popup_thread.join(timeout=3)
            logger.info("Popup watcher stopped")

    def _popup_watch_loop(self, interval: float):
        """Background loop to dismiss popups."""
        while not self._stop_event.is_set():
            try:
                self._dismiss_popup()
            except Exception:
                pass
            self._stop_event.wait(interval)

    def _dismiss_popup(self):
        """Try to dismiss any visible popup."""
        for pattern in POPUP_DISMISS_PATTERNS:
            element = self.device(**pattern)
            if element.exists(timeout=0.3):
                element.click()
                logger.info("Dismissed popup: {}", pattern)
                time.sleep(0.3)
                return True
        return False

    def ensure_in_app(self):
        """Make sure we're still in Damai app, restart if needed."""
        try:
            current = self.device.app_current()
            if current.get("package") != DAMAI_PACKAGE:
                logger.warning("Left Damai app (current: {}), restarting...",
                             current.get("package"))
                self.device.app_start(DAMAI_PACKAGE)
                time.sleep(3)
                return False
        except Exception as e:
            logger.warning("Failed to check app state: {}", e)
        return True

    def press_back_to_recover(self, max_backs: int = 3):
        """Press back multiple times to try to recover from error state."""
        for i in range(max_backs):
            logger.info("Recovery: pressing back ({}/{})", i + 1, max_backs)
            self.device.press("back")
            time.sleep(0.5)

            # Check if we're back in a known good state
            if self.ensure_in_app():
                return True

        return False

    def retry_step(self, func, step_name: str, max_retries: int = 3, delay: float = 1.0):
        """Retry a step function with recovery.

        Args:
            func: Callable that returns True on success, False on failure
            step_name: Name of the step (for logging)
            max_retries: Maximum retry attempts
            delay: Delay between retries in seconds

        Returns:
            True if step succeeded, False if all retries failed.
        """
        for attempt in range(1, max_retries + 1):
            try:
                result = func()
                if result:
                    return True
                logger.warning("Step '{}' failed (attempt {}/{})", step_name, attempt, max_retries)
            except Exception as e:
                logger.warning("Step '{}' error (attempt {}/{}): {}", step_name, attempt, max_retries, e)

            if attempt < max_retries:
                self._dismiss_popup()  # Try dismissing popups before retry
                time.sleep(delay)

        logger.error("Step '{}' failed after {} attempts", step_name, max_retries)
        return False
