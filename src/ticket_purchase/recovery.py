"""异常恢复：弹窗关闭、步骤重试、页面导航。"""
import json
import os
import threading
import time

import uiautomator2 as u2
from loguru import logger

# 常见弹窗关闭按钮匹配模式（LLM 失败时的回退）
POPUP_DISMISS_PATTERNS = [
    # 弹窗专用关闭按钮 (resourceId 最可靠)
    {"resourceId": "cn.damai:id/btn_close"},
    {"resourceId": "cn.damai:id/iv_close"},
    {"resourceId": "cn.damai:id/dialog_close"},
    {"resourceId": "cn.damai:id/close_btn"},
    # 明确的弹窗文本按钮
    {"text": "我知道了"},
    {"text": "知道了"},
    {"text": "暂不"},
    {"text": "跳过"},
    {"text": "不再提醒"},
    {"text": "以后再说"},
    {"text": "稍后再说"},
    {"textContains": "同意并继续"},
    # 注意：不要加 "取消"、"关闭" 等通用词
]

# LLM 弹窗检测 prompt
_POPUP_DETECT_PROMPT = """分析以下 Android UI XML，判断是否有弹窗需要关闭。

重要：Android XML 中，**最后出现的元素在最上层**（后绘制覆盖先绘制）。
弹窗作为覆盖层，通常出现在 XML 末尾部分。请重点分析 XML 末尾的元素。

弹窗特征：
- XML 末尾出现的 FrameLayout/LinearLayout 包含按钮
- 包含 "知道了"、"我知道了"、"确定"、"取消"、"关闭"、"同意" 等文本的按钮
- 可能有 dialog、popup、alert 等关键词的 resourceId
- bounds 坐标显示居中或覆盖大部分屏幕

不是弹窗的情况：
- 搜索页面顶部的"取消"按钮（通常在 XML 开头）
- 页面正常的功能按钮
- 底部导航栏

只输出 JSON:
{{"has_popup": true/false, "dismiss_strategy": "resourceId"|"text"|"none", "dismiss_value": "用于定位关闭按钮的值", "reason": "简短说明"}}

XML (末尾部分是最上层):
{xml}"""

DAMAI_PACKAGE = "cn.damai"


class RecoveryManager:
    """管理异常恢复和弹窗关闭。"""

    def __init__(self, device: u2.Device, llm_client=None):
        self.device = device
        self._llm = llm_client
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
        """尝试关闭任何可见弹窗，优先使用 LLM 判断。"""
        # Strategy 1: LLM 智能判断
        if self._llm and self._llm.enabled:
            result = self._llm_detect_popup()
            if result:
                has_popup = result.get("has_popup", False)
                if not has_popup:
                    return False  # LLM 判断没有弹窗

                strategy = result.get("dismiss_strategy", "none")
                value = result.get("dismiss_value", "")
                reason = result.get("reason", "")

                if strategy != "none" and value:
                    selector = {strategy: value}
                    element = self.device(**selector)
                    if element.exists(timeout=0.5):
                        element.click()
                        logger.info("LLM 关闭弹窗: {} ({})", selector, reason)
                        time.sleep(0.3)
                        return True
                    else:
                        logger.debug("LLM 建议的元素不存在: {}", selector)

        # Strategy 2: 规则匹配回退
        for pattern in POPUP_DISMISS_PATTERNS:
            element = self.device(**pattern)
            if element.exists(timeout=0.3):
                element.click()
                logger.info("规则关闭弹窗: {}", pattern)
                time.sleep(0.3)
                return True
        return False

    def _llm_detect_popup(self) -> dict | None:
        """使用 LLM 分析页面是否有弹窗。"""
        try:
            xml_full = self.device.dump_hierarchy()
            xml_len = len(xml_full)
            # 弹窗在最上层，对应 XML 末尾。只取末尾 20000 字符
            if xml_len > 20000:
                xml = xml_full[-20000:]
            else:
                xml = xml_full
            logger.debug("弹窗检测 XML: 总长={}, 取末尾={}", xml_len, len(xml))
            prompt = _POPUP_DETECT_PROMPT.format(xml=xml)

            response = self._llm.chat(prompt)
            if not response:
                return None

            # 提取 JSON
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            result = json.loads(json_str)
            logger.debug("LLM 弹窗检测: {}", result)
            return result
        except Exception as e:
            logger.debug("LLM 弹窗检测失败: {}", e)
            return None

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
