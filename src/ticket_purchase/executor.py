"""UI action execution: tap, click, swipe, input."""
import uiautomator2 as u2
from loguru import logger


class Executor:
    """Executes UI operations on the device."""

    def __init__(self, device: u2.Device):
        self.device = device

    def tap(self, x: int, y: int):
        """Tap at specific coordinates (fastest method)."""
        logger.debug("Tap ({}, {})", x, y)
        self.device.click(x, y)

    def click(self, element: u2.UiObject):
        """Click a UI element."""
        try:
            info = element.info
            bounds = info.get("bounds", {})
            # Calculate center for coordinate-based click (faster)
            cx = (bounds.get("left", 0) + bounds.get("right", 0)) // 2
            cy = (bounds.get("top", 0) + bounds.get("bottom", 0)) // 2
            if cx > 0 and cy > 0:
                self.device.click(cx, cy)
                logger.debug("Click element at ({}, {})", cx, cy)
                return
        except Exception as e:
            logger.debug("Coordinate click failed, using fallback: {}", e)

        # Fallback to element click
        element.click()
        logger.debug("Click element (fallback)")

    def swipe(self, direction: str = "up", scale: float = 0.5):
        """Swipe in a direction.

        Args:
            direction: "up", "down", "left", "right"
            scale: Swipe distance as fraction of screen (0.0-1.0)
        """
        logger.debug("Swipe {} (scale={})", direction, scale)
        self.device.swipe_ext(direction, scale=scale)

    def input_text(self, element: u2.UiObject, text: str):
        """Clear and input text into an element."""
        element.clear_text()
        element.set_text(text)
        logger.debug("Input text: '{}'", text)

    def press_key(self, key: str):
        """Press a key (e.g. 'enter', 'back', 'home')."""
        logger.debug("Press key: {}", key)
        self.device.press(key)

    def press_back(self):
        """Press the back button."""
        self.press_key("back")
