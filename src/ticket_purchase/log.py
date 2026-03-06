"""日志与截图管理。"""
import os
from datetime import datetime
from pathlib import Path

from loguru import logger

# 基础目录
BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOG_DIR = BASE_DIR / "logs"
SCREENSHOT_DIR = BASE_DIR / "screenshots"


def setup_logging(level: str = "INFO"):
    """配置 loguru：控制台（彩色）+ 滚动日志文件。"""
    LOG_DIR.mkdir(exist_ok=True)
    SCREENSHOT_DIR.mkdir(exist_ok=True)

    # 移除默认处理器
    logger.remove()

    # 控制台：彩色、简洁
    import sys
    logger.add(
        sink=sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
        colorize=True,
    )

    # 文件：滚动、详细
    logger.add(
        LOG_DIR / "ticket_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<7} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention="7 days",
        encoding="utf-8",
    )

    logger.info("日志已初始化，级别={}", level)


def take_screenshot(device, name: str = "debug") -> str | None:
    """从设备截图并保存到截图目录。"""
    try:
        SCREENSHOT_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{name}_{timestamp}.png"
        filepath = SCREENSHOT_DIR / filename
        image = device.screenshot()
        image.save(str(filepath))
        logger.info("截图已保存: {}", filepath)
        return str(filepath)
    except Exception as e:
        logger.warning("截图失败: {}", e)
        return None
