"""ADB 无线连接与 uiautomator2 设备初始化。"""
import subprocess
import time

import uiautomator2 as u2
from loguru import logger


def adb_connect(ip: str, port: int = 5555, max_retries: int = 3) -> bool:
    """通过 ADB 无线连接设备。

    连接成功返回 True。
    """
    addr = f"{ip}:{port}"
    for attempt in range(1, max_retries + 1):
        logger.info("ADB 正在连接 {} (第 {}/{} 次尝试)", addr, attempt, max_retries)
        try:
            result = subprocess.run(
                ["adb", "connect", addr],
                capture_output=True, text=True, timeout=10,
            )
            output = result.stdout.strip()
            logger.debug("ADB 输出: {}", output)

            if "connected" in output.lower():
                logger.info("ADB 已连接: {}", addr)
                return True

            logger.warning("ADB 连接失败: {}", output)
        except subprocess.TimeoutExpired:
            logger.warning("ADB 连接超时")
        except FileNotFoundError:
            logger.error("未找到 adb 命令，请确保已安装 Android platform-tools")
            return False

        if attempt < max_retries:
            time.sleep(2)

    logger.error("ADB 连接在 {} 次尝试后失败", max_retries)
    return False


def init_device(ip: str, port: int = 5555) -> u2.Device:
    """初始化 uiautomator2 设备连接。

    先通过 ADB 连接，然后创建 u2 设备对象。
    连接失败时抛出 ConnectionError。
    """
    if not adb_connect(ip, port):
        raise ConnectionError(f"Cannot connect to device {ip}:{port}")

    addr = f"{ip}:{port}"
    logger.info("正在初始化 u2 设备: {}", addr)
    device = u2.connect(addr)

    # 验证连接
    info = device.info
    logger.info("设备已连接: {} ({}x{})",
                info.get("productName", "unknown"),
                info.get("displayWidth", "?"),
                info.get("displayHeight", "?"))

    # 优化设置以提升速度
    device.settings["wait_timeout"] = 3.0
    device.settings["operation_delay"] = (0, 0)
    device.settings["operation_delay_methods"] = []

    # 先禁用监听器（后续在恢复模块中添加自定义监听器）
    device.watcher.remove()

    return device
