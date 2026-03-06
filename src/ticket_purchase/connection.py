"""ADB wireless connection and uiautomator2 device initialization."""
import subprocess
import time

import uiautomator2 as u2
from loguru import logger


def adb_connect(ip: str, port: int = 5555, max_retries: int = 3) -> bool:
    """Connect to device via ADB wireless.

    Returns True if connected successfully.
    """
    addr = f"{ip}:{port}"
    for attempt in range(1, max_retries + 1):
        logger.info("ADB connecting to {} (attempt {}/{})", addr, attempt, max_retries)
        try:
            result = subprocess.run(
                ["adb", "connect", addr],
                capture_output=True, text=True, timeout=10,
            )
            output = result.stdout.strip()
            logger.debug("ADB output: {}", output)

            if "connected" in output.lower():
                logger.info("ADB connected to {}", addr)
                return True

            logger.warning("ADB connect failed: {}", output)
        except subprocess.TimeoutExpired:
            logger.warning("ADB connect timeout")
        except FileNotFoundError:
            logger.error("adb command not found, ensure Android platform-tools is installed")
            return False

        if attempt < max_retries:
            time.sleep(2)

    logger.error("ADB connect failed after {} attempts", max_retries)
    return False


def init_device(ip: str, port: int = 5555) -> u2.Device:
    """Initialize uiautomator2 device connection.

    Connects via ADB first, then creates u2 device object.
    Raises ConnectionError if connection fails.
    """
    if not adb_connect(ip, port):
        raise ConnectionError(f"Cannot connect to device {ip}:{port}")

    addr = f"{ip}:{port}"
    logger.info("Initializing u2 device: {}", addr)
    device = u2.connect(addr)

    # Verify connection
    info = device.info
    logger.info("Device connected: {} ({}x{})",
                info.get("productName", "unknown"),
                info.get("displayWidth", "?"),
                info.get("displayHeight", "?"))

    # Optimize settings for speed
    device.settings["wait_timeout"] = 3.0
    device.settings["operation_delay"] = (0, 0)
    device.settings["operation_delay_methods"] = []

    # Disable watchers initially (we'll add our own in recovery)
    device.watcher.remove()

    return device
