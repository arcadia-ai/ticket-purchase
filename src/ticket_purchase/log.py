"""Logging and screenshot management."""
import os
from datetime import datetime
from pathlib import Path

from loguru import logger

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOG_DIR = BASE_DIR / "logs"
SCREENSHOT_DIR = BASE_DIR / "screenshots"


def setup_logging(level: str = "INFO"):
    """Configure loguru: console (colored) + rotating file."""
    LOG_DIR.mkdir(exist_ok=True)
    SCREENSHOT_DIR.mkdir(exist_ok=True)

    # Remove default handler
    logger.remove()

    # Console: colored, concise
    import sys
    logger.add(
        sink=sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
        colorize=True,
    )

    # File: rotating, detailed
    logger.add(
        LOG_DIR / "ticket_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<7} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention="7 days",
        encoding="utf-8",
    )

    logger.info("Logging initialized, level={}", level)


def take_screenshot(device, name: str = "debug") -> str | None:
    """Capture screenshot from device and save to screenshots dir."""
    try:
        SCREENSHOT_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{name}_{timestamp}.png"
        filepath = SCREENSHOT_DIR / filename
        image = device.screenshot()
        image.save(str(filepath))
        logger.info("Screenshot saved: {}", filepath)
        return str(filepath)
    except Exception as e:
        logger.warning("Screenshot failed: {}", e)
        return None
