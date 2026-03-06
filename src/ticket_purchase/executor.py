"""UI 操作执行：点击、滑动、输入。"""
import uiautomator2 as u2
from loguru import logger


class Executor:
    """在设备上执行 UI 操作。"""

    def __init__(self, device: u2.Device):
        self.device = device

    def tap(self, x: int, y: int):
        """坐标点击（最快方式）。"""
        logger.debug("点击坐标 ({}, {})", x, y)
        self.device.click(x, y)

    def click(self, element: u2.UiObject):
        """点击 UI 元素。"""
        try:
            info = element.info
            bounds = info.get("bounds", {})
            # 计算中心坐标进行点击（更快）
            cx = (bounds.get("left", 0) + bounds.get("right", 0)) // 2
            cy = (bounds.get("top", 0) + bounds.get("bottom", 0)) // 2
            if cx > 0 and cy > 0:
                self.device.click(cx, cy)
                logger.debug("点击元素坐标 ({}, {})", cx, cy)
                return
        except Exception as e:
            logger.debug("坐标点击失败，使用备用方式: {}", e)

        # 备用方式：元素点击
        element.click()
        logger.debug("点击元素（备用方式）")

    def swipe(self, direction: str = "up", scale: float = 0.5):
        """向指定方向滑动。

        Args:
            direction: "up"、"down"、"left"、"right"
            scale: 滑动距离占屏幕比例 (0.0-1.0)
        """
        logger.debug("滑动 {} (比例={})", direction, scale)
        self.device.swipe_ext(direction, scale=scale)

    def input_text(self, element: u2.UiObject, text: str):
        """清除并向元素输入文本。"""
        element.clear_text()
        element.set_text(text)
        logger.debug("输入文本: '{}'", text)

    def press_key(self, key: str):
        """按下按键（如 'enter'、'back'、'home'）。"""
        logger.debug("按键: {}", key)
        self.device.press(key)

    def press_back(self):
        """按下返回键。"""
        self.press_key("back")
