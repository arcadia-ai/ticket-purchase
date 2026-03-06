"""Screen monitoring and page state detection."""
import time

import uiautomator2 as u2
from loguru import logger

DAMAI_PACKAGE = "cn.damai"


def wait_for_element(device: u2.Device, timeout: float = 5.0, **kwargs) -> u2.UiObject | None:
    """Wait for a UI element to appear.

    Args:
        device: u2 device
        timeout: max wait time in seconds
        **kwargs: u2 selector kwargs (resourceId, text, className, etc.)

    Returns:
        UiObject if found, None if timeout.
    """
    element = device(**kwargs)
    if element.wait(timeout=timeout):
        return element
    return None


def is_damai_foreground(device: u2.Device) -> bool:
    """Check if Damai app is in foreground."""
    try:
        current = device.app_current()
        return current.get("package") == DAMAI_PACKAGE
    except Exception:
        return False


def ensure_damai_running(device: u2.Device):
    """Make sure Damai app is running in foreground."""
    if not is_damai_foreground(device):
        logger.info("Starting Damai app...")
        device.app_start(DAMAI_PACKAGE)
        time.sleep(3)  # Wait for app to load
        if not is_damai_foreground(device):
            raise RuntimeError("Failed to start Damai app")
        logger.info("Damai app started")
    else:
        logger.info("Damai app already in foreground")


def get_page_xml(device: u2.Device, max_length: int = 15000) -> str:
    """Get current page XML source (truncated for LLM use)."""
    try:
        xml = device.dump_hierarchy()
        return xml[:max_length]
    except Exception as e:
        logger.warning("Failed to get page XML: {}", e)
        return ""
