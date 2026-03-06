"""屏幕监控与页面状态检测。"""
import time

import uiautomator2 as u2
from loguru import logger

DAMAI_PACKAGE = "cn.damai"


def wait_for_element(device: u2.Device, timeout: float = 5.0, **kwargs) -> u2.UiObject | None:
    """等待 UI 元素出现。

    Args:
        device: u2 设备
        timeout: 最大等待时间（秒）
        **kwargs: u2 选择器参数（resourceId、text、className 等）

    Returns:
        找到则返回 UiObject，超时返回 None。
    """
    element = device(**kwargs)
    if element.wait(timeout=timeout):
        return element
    return None


def is_damai_foreground(device: u2.Device) -> bool:
    """检查大麦 App 是否在前台运行。"""
    try:
        current = device.app_current()
        return current.get("package") == DAMAI_PACKAGE
    except Exception:
        return False


def ensure_damai_running(device: u2.Device):
    """确保大麦 App 在前台运行。"""
    if not is_damai_foreground(device):
        logger.info("正在启动大麦 App...")
        device.app_start(DAMAI_PACKAGE)
        time.sleep(3)  # 等待应用加载
        if not is_damai_foreground(device):
            raise RuntimeError("启动大麦 App 失败")
        logger.info("大麦 App 已启动")
    else:
        logger.info("大麦 App 已在前台运行")


def get_page_xml(device: u2.Device, max_length: int = 15000) -> str:
    """获取当前页面 XML 源码（截断以供 LLM 使用）。"""
    try:
        xml = device.dump_hierarchy()
        return xml[:max_length]
    except Exception as e:
        logger.warning("获取页面 XML 失败: {}", e)
        return ""
