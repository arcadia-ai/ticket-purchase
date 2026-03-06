"""精准调度：NTP 时间同步 + 倒计时定时器。"""
import time
from datetime import datetime

from loguru import logger


def get_ntp_offset() -> float:
    """获取 NTP 服务器时间偏移。

    返回偏移量（秒），local_time + offset = 精确时间。
    NTP 同步失败时返回 0.0。
    """
    try:
        import ntplib
        client = ntplib.NTPClient()
        # 尝试多个 NTP 服务器
        servers = ["ntp.aliyun.com", "ntp.tencent.com", "pool.ntp.org"]
        for server in servers:
            try:
                response = client.request(server, timeout=3)
                offset = response.offset
                logger.info("NTP 已同步: {} (偏移: {:.3f}秒)", server, offset)
                return offset
            except Exception:
                continue
        logger.warning("所有 NTP 服务器均失败，使用本地时间")
    except ImportError:
        logger.warning("ntplib 未安装，使用本地时间")
    return 0.0


def accurate_now(offset: float = 0.0) -> datetime:
    """获取经 NTP 偏移校正后的当前时间。"""
    return datetime.fromtimestamp(time.time() + offset)


def wait_until(target_time_str: str):
    """精确等待至目标时间。

    使用粗略休眠（>1秒）+ 忙等待（<1秒）实现毫秒级精度。

    Args:
        target_time_str: 目标时间，格式为 "YYYY-MM-DD HH:MM:SS"
    """
    if not target_time_str or not target_time_str.strip():
        logger.info("未设置目标时间，立即执行")
        return

    target = datetime.strptime(target_time_str.strip(), "%Y-%m-%d %H:%M:%S")
    ntp_offset = get_ntp_offset()
    now = accurate_now(ntp_offset)

    if now >= target:
        logger.info("目标时间 {} 已过，立即执行", target_time_str)
        return

    diff = (target - now).total_seconds()
    logger.info("等待目标时间: {} (还剩 {:.1f}秒)", target_time_str, diff)

    # 阶段一：粗略休眠（节省 CPU）— 休眠到目标时间前 1 秒
    while True:
        now = accurate_now(ntp_offset)
        remaining = (target - now).total_seconds()
        if remaining <= 1.0:
            break
        if remaining > 10:
            logger.info("倒计时: 还剩 {:.0f}秒", remaining)
            time.sleep(min(remaining - 1.0, 5.0))
        else:
            time.sleep(0.1)

    # 阶段二：忙等待以提升精度（最后约 1 秒）
    logger.info("进入精确等待...")
    while accurate_now(ntp_offset) < target:
        pass  # 忙等待以达到毫秒级精度

    logger.info("已到达目标时间！立即执行。")
