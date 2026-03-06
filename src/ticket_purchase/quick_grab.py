"""极简快速抢票循环（手动进入购票页面后使用）。

使用方式：
1. 手动打开大麦 App，进入目标演出的购票页面
2. 手动预填好观演人信息
3. 运行此脚本开始自动抢票循环

每个循环预计耗时：300-500ms
"""
import time
from loguru import logger


class QuickGrabWorkflow:
    """快速抢票循环。"""

    # 不可购买的标识
    UNAVAILABLE_KEYWORDS = ["无票", "售罄", "缺货登记", "缺货", "暂无", "不可售"]

    def __init__(self, device):
        self.device = device
        self._loop_count = 0
        self._start_time = None

    def run(self, max_loops: int = 1000, loop_delay: float = 0.05) -> bool:
        """执行快速抢票循环。

        Args:
            max_loops: 最大循环次数
            loop_delay: 每次循环间隔（秒）

        Returns:
            成功返回 True
        """
        logger.info("=" * 50)
        logger.info("快速抢票模式启动")
        logger.info("请确保已手动进入购票页面并预填观演人")
        logger.info("=" * 50)

        self._start_time = time.time()

        for i in range(max_loops):
            self._loop_count = i + 1
            loop_start = time.time()

            try:
                # 步骤1: 选择有票的日期/场次/票档
                if not self._select_available_options():
                    time.sleep(loop_delay)
                    continue

                # 步骤2: 点击确定
                self._click_confirm()

                # 步骤3: 提交订单
                if self._submit_order():
                    elapsed = time.time() - self._start_time
                    logger.info("=" * 50)
                    logger.info("抢票成功！循环 {} 次，总耗时 {:.2f}秒", self._loop_count, elapsed)
                    logger.info("=" * 50)
                    return True

                # 提交失败，返回重试
                self._go_back()

            except Exception as e:
                logger.debug("循环 {} 出错: {}", self._loop_count, e)
                self._go_back()

            loop_time = (time.time() - loop_start) * 1000
            if self._loop_count % 50 == 0:
                logger.info("已循环 {} 次，本次耗时 {:.0f}ms", self._loop_count, loop_time)

            time.sleep(loop_delay)

        logger.error("达到最大循环次数 {}，抢票失败", max_loops)
        return False

    def _select_available_options(self) -> bool:
        """选择有票的日期/场次/票档。"""
        # 查找所有可能的选项容器
        # 策略：找到可点击的元素，排除包含不可购买关键词的

        # 尝试点击场次/日期（通常是第一组选项）
        clicked_session = self._click_first_available(
            desc="场次",
            container_id="cn.damai:id/perform_list",  # 场次列表容器
            fallback_class="android.widget.LinearLayout",
        )

        # 尝试点击票档（通常是第二组选项）
        clicked_price = self._click_first_available(
            desc="票档",
            container_id="cn.damai:id/project_detail_perform_price_flowlayout",
            fallback_class="android.widget.FrameLayout",
        )

        return clicked_session or clicked_price

    def _click_first_available(self, desc: str, container_id: str, fallback_class: str) -> bool:
        """点击第一个可购买的选项。"""
        # 方法1：通过容器 ID 查找
        try:
            container = self.device(resourceId=container_id)
            if container.exists(timeout=0.1):
                # 遍历子元素，找到不包含不可购买关键词的
                children = container.child(className=fallback_class)
                for i in range(min(children.count, 10)):
                    child = children[i]
                    if child.exists:
                        text = child.info.get("text", "") or ""
                        # 获取子元素的所有文本
                        try:
                            child_texts = self._get_all_text(child)
                        except:
                            child_texts = text

                        # 检查是否可购买
                        if not self._is_unavailable(child_texts):
                            child.click()
                            logger.debug("选择{}: {}", desc, child_texts[:30] if child_texts else "item")
                            return True
        except Exception as e:
            logger.debug("容器查找失败 {}: {}", container_id, e)

        # 方法2：直接查找可购买的文本
        for keyword in ["有票", "预售", "¥", "元"]:
            try:
                element = self.device(textContains=keyword)
                if element.exists(timeout=0.05):
                    # 验证不是不可购买状态
                    text = element.info.get("text", "")
                    if not self._is_unavailable(text):
                        element.click()
                        logger.debug("选择{}: {}", desc, keyword)
                        return True
            except:
                pass

        return False

    def _get_all_text(self, element) -> str:
        """获取元素及其子元素的所有文本。"""
        try:
            info = element.info
            texts = [info.get("text", "") or ""]
            # 简化：只获取当前元素文本
            return " ".join(texts)
        except:
            return ""

    def _is_unavailable(self, text: str) -> bool:
        """检查是否为不可购买状态。"""
        if not text:
            return False
        text_lower = text.lower()
        return any(kw in text_lower for kw in self.UNAVAILABLE_KEYWORDS)

    def _click_confirm(self):
        """点击确定按钮。"""
        # 尝试多种确定按钮
        confirm_selectors = [
            {"text": "确定"},
            {"text": "确认"},
            {"textContains": "立即"},
            {"resourceId": "cn.damai:id/btn_buy"},
        ]

        for selector in confirm_selectors:
            try:
                btn = self.device(**selector)
                if btn.exists(timeout=0.05):
                    btn.click()
                    logger.debug("点击确定: {}", selector)
                    return True
            except:
                pass

        return False

    def _submit_order(self) -> bool:
        """提交订单。"""
        time.sleep(0.1)  # 短暂等待页面响应

        # 尝试提交按钮
        submit_selectors = [
            {"text": "立即提交"},
            {"text": "提交订单"},
            {"textContains": "提交"},
            {"textContains": "支付"},
        ]

        for selector in submit_selectors:
            try:
                btn = self.device(**selector)
                if btn.exists(timeout=0.1):
                    btn.click()
                    logger.info("点击提交订单")
                    time.sleep(0.2)

                    # 检查是否成功（没有错误提示）
                    error = self.device(textContains="失败")
                    if not error.exists(timeout=0.1):
                        # 检查是否进入支付页面
                        pay = self.device(textContains="支付")
                        if pay.exists(timeout=0.2):
                            return True

                    return False
            except:
                pass

        return False

    def _go_back(self):
        """返回上一页重试。"""
        try:
            self.device.press("back")
            time.sleep(0.1)
        except:
            pass


def main():
    """快速抢票入口。"""
    import os
    import sys
    from pathlib import Path

    from dotenv import load_dotenv

    # 加载环境变量
    base_dir = Path(__file__).resolve().parent.parent.parent
    env_path = base_dir / "config" / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    # 设置日志
    from .log import setup_logging
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))

    # 连接设备
    from .connection import init_device
    device_ip = os.getenv("DEVICE_IP", "127.0.0.1")
    device_port = int(os.getenv("DEVICE_PORT", "5555"))

    try:
        device = init_device(device_ip, device_port)
    except ConnectionError as e:
        logger.error("设备连接失败: {}", e)
        sys.exit(1)

    # 执行快速抢票
    workflow = QuickGrabWorkflow(device)
    success = workflow.run(max_loops=1000, loop_delay=0.05)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
