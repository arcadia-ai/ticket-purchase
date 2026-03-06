"""异常恢复：弹窗关闭、步骤重试、页面导航。"""
import threading
import time

import uiautomator2 as u2
from loguru import logger

# 常见弹窗关闭按钮匹配模式
POPUP_DISMISS_PATTERNS = [
    {"text": "我知道了"},
    {"text": "知道了"},
    {"text": "关闭"},
    {"text": "取消"},
    {"text": "暂不"},
    {"text": "跳过"},
    {"text": "不再提醒"},
    {"textContains": "同意"},
    {"resourceId": "cn.damai:id/btn_close"},
    {"resourceId": "cn.damai:id/iv_close"},
    {"description": "关闭"},
]

DAMAI_PACKAGE = "cn.damai"


class RecoveryManager:
    """管理异常恢复和弹窗关闭。"""

    def __init__(self, device: u2.Device):
        self.device = device
        self._popup_thread = None
        self._stop_event = threading.Event()

    def start_popup_watcher(self, interval: float = 1.5):
        """启动后台线程自动关闭弹窗。"""
        if self._popup_thread and self._popup_thread.is_alive():
            return

        self._stop_event.clear()
        self._popup_thread = threading.Thread(
            target=self._popup_watch_loop,
            args=(interval,),
            daemon=True,
        )
        self._popup_thread.start()
        logger.info("弹窗监听已启动 (间隔={}秒)", interval)

    def stop_popup_watcher(self):
        """停止弹窗监听线程。"""
        self._stop_event.set()
        if self._popup_thread:
            self._popup_thread.join(timeout=3)
            logger.info("弹窗监听已停止")

    def _popup_watch_loop(self, interval: float):
        """后台循环关闭弹窗。"""
        while not self._stop_event.is_set():
            try:
                self._dismiss_popup()
            except Exception:
                pass
            self._stop_event.wait(interval)

    def _dismiss_popup(self):
        """尝试关闭任何可见弹窗。"""
        for pattern in POPUP_DISMISS_PATTERNS:
            element = self.device(**pattern)
            if element.exists(timeout=0.3):
                element.click()
                logger.info("已关闭弹窗: {}", pattern)
                time.sleep(0.3)
                return True
        return False

    def ensure_in_app(self):
        """确保仍在大麦 App 内，必要时重启。"""
        try:
            current = self.device.app_current()
            if current.get("package") != DAMAI_PACKAGE:
                logger.warning("已离开大麦 App (当前: {})，正在重启...",
                             current.get("package"))
                self.device.app_start(DAMAI_PACKAGE)
                time.sleep(3)
                return False
        except Exception as e:
            logger.warning("检查应用状态失败: {}", e)
        return True

    def press_back_to_recover(self, max_backs: int = 3):
        """多次按返回键尝试从错误状态恢复。"""
        for i in range(max_backs):
            logger.info("恢复中: 按返回键 ({}/{})", i + 1, max_backs)
            self.device.press("back")
            time.sleep(0.5)

            # 检查是否已恢复到正常状态
            if self.ensure_in_app():
                return True

        return False

    def retry_step(self, func, step_name: str, max_retries: int = 3, delay: float = 1.0):
        """带恢复机制的步骤重试。

        Args:
            func: 可调用对象，成功返回 True，失败返回 False
            step_name: 步骤名称（用于日志记录）
            max_retries: 最大重试次数
            delay: 重试间隔时间（秒）

        Returns:
            步骤成功返回 True，所有重试失败返回 False。
        """
        for attempt in range(1, max_retries + 1):
            try:
                result = func()
                if result:
                    return True
                logger.warning("步骤 '{}' 失败 (第 {}/{} 次尝试)", step_name, attempt, max_retries)
            except Exception as e:
                logger.warning("步骤 '{}' 出错 (第 {}/{} 次尝试): {}", step_name, attempt, max_retries, e)

            if attempt < max_retries:
                self._dismiss_popup()  # 重试前尝试关闭弹窗
                time.sleep(delay)

        logger.error("步骤 '{}' 在 {} 次尝试后失败", step_name, max_retries)
        return False
