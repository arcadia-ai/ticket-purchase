"""Precision scheduling: NTP time sync + countdown timer."""
import time
from datetime import datetime

from loguru import logger


def get_ntp_offset() -> float:
    """Get time offset from NTP server.

    Returns offset in seconds (local_time + offset = accurate_time).
    Returns 0.0 if NTP sync fails.
    """
    try:
        import ntplib
        client = ntplib.NTPClient()
        # Try multiple NTP servers
        servers = ["ntp.aliyun.com", "ntp.tencent.com", "pool.ntp.org"]
        for server in servers:
            try:
                response = client.request(server, timeout=3)
                offset = response.offset
                logger.info("NTP synced with {} (offset: {:.3f}s)", server, offset)
                return offset
            except Exception:
                continue
        logger.warning("All NTP servers failed, using local time")
    except ImportError:
        logger.warning("ntplib not installed, using local time")
    return 0.0


def accurate_now(offset: float = 0.0) -> datetime:
    """Get current time with NTP offset correction."""
    return datetime.fromtimestamp(time.time() + offset)


def wait_until(target_time_str: str):
    """Wait until the target time with precision.

    Uses coarse sleep (>1s away) + busy-wait (<1s) for ms-level accuracy.

    Args:
        target_time_str: Target time in format "YYYY-MM-DD HH:MM:SS"
    """
    if not target_time_str or not target_time_str.strip():
        logger.info("No target time set, running immediately")
        return

    target = datetime.strptime(target_time_str.strip(), "%Y-%m-%d %H:%M:%S")
    ntp_offset = get_ntp_offset()
    now = accurate_now(ntp_offset)

    if now >= target:
        logger.info("Target time {} already passed, running immediately", target_time_str)
        return

    diff = (target - now).total_seconds()
    logger.info("Waiting for target time: {} ({:.1f}s away)", target_time_str, diff)

    # Phase 1: Coarse sleep (save CPU) — sleep until 1s before target
    while True:
        now = accurate_now(ntp_offset)
        remaining = (target - now).total_seconds()
        if remaining <= 1.0:
            break
        if remaining > 10:
            logger.info("Countdown: {:.0f}s remaining", remaining)
            time.sleep(min(remaining - 1.0, 5.0))
        else:
            time.sleep(0.1)

    # Phase 2: Busy-wait for precision (last ~1 second)
    logger.info("Entering precision wait...")
    while accurate_now(ntp_offset) < target:
        pass  # Busy-wait for ms-level precision

    logger.info("Target time reached! Executing now.")
