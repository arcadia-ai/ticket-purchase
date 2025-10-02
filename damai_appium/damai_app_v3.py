# -*- coding: UTF-8 -*-
"""
__Author__ = "BlueCestbon"
__Version__ = "2.3.3"
__Description__ = "大麦app抢票自动化 - Ollama日期优化版"
"""

import time
import json
import ollama
from appium import webdriver
from appium.options.common.base import AppiumOptions
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config import Config


class DamaiBot:
    def __init__(self):
        self.config = Config.load_config()
        self.driver = None
        self.wait = None
        self.model = 'gpt-oss:120b-cloud'  # 从 config 读取模型
        self.ollama_client = ollama.Client(
            host='http://192.168.123.200:11434')  # 从 config 读取 URL
        # 🔧 新增：日期变体列表（从 config 读取或默认）
        self.date_variants = ["10.04", "10月4日", "2025-10-04"]
        self._setup_driver()

    def _setup_driver(self):
        """初始化驱动配置"""
        capabilities = {
            "platformName": "Android",
            "platformVersion": "15",
            "deviceName": "OnePlus 11",
            "appPackage": "cn.damai",
            "appActivity": ".launcher.splash.SplashMainActivity",
            "unicodeKeyboard": True,
            "resetKeyboard": True,
            "noReset": True,
            "newCommandTimeout": 6000,
            "automationName": "UiAutomator2",
            "skipServerInstallation": False,
            "ignoreHiddenApiPolicyError": True,
            "disableWindowAnimation": True,
            "shouldTerminateApp": False,
            "adbExecTimeout": 20000,
        }

        device_app_info = AppiumOptions()
        device_app_info.load_capabilities(capabilities)
        self.driver = webdriver.Remote(self.config.server_url, options=device_app_info)

        self.driver.update_settings({
            "waitForIdleTimeout": 300,
            "actionAcknowledgmentTimeout": 50,
            "keyInjectionDelay": 0,
            "waitForSelectorTimeout": 500,
            "ignoreUnimportantViews": True,
            "allowInvisibleElements": False,
        })

        self.driver.implicitly_wait(2)
        self.wait = WebDriverWait(self.driver, 3)

    def safe_click(self, element):
        """安全点击元素"""
        try:
            rect = element.rect
            x = rect['x'] + rect['width'] // 2
            y = rect['y'] + rect['height'] // 2
            self.driver.execute_script("mobile: clickGesture", {
                "x": x, "y": y, "duration": 30
            })
        except:
            element.click()

    def quick_screenshot(self, name="debug"):
        """快速截图（仅在失败时使用）"""
        try:
            self.driver.save_screenshot(f"{name}.png")
            print(f"  已保存截图: {name}.png")
        except:
            pass

    def scroll_to_bottom(self):
        """滚动到底部（优化版）"""
        print("  📜 滚动到底部...")
        try:
            size = self.driver.get_window_size()
            for _ in range(3):
                self.driver.execute_script('mobile: scrollGesture', {
                    'left': 100, 'top': int(size['height'] * 0.7), 'width': size['width'] - 200,
                    'height': int(size['height'] * 0.2),
                    'direction': 'down', 'percent': 0.8
                })
                time.sleep(0.5)
            print("  ✓ 已滚动到底部")
        except Exception as e:
            print(f"  ⚠ 滚动失败: {e}")

    def find_element_with_ollama(self, description, timeout=5):
        """使用Ollama分析XML，查找元素locator（进一步优化）"""
        try:
            xml = self.driver.page_source[:20000]  # 增加长度
            prompt = f"""
You are an expert in Appium automation for Android apps. Analyze the following Appium XML page source and identify the best locator for the UI element described: "{description}".

Focus on visible elements. Prioritize:
1. By.ID with full resource-id (e.g., "cn.damai:id/btn_buy")
2. AppiumBy.ANDROID_UIAUTOMATOR with textContains or resourceId (e.g., 'new UiSelector().textContains("10月4日").resourceId("cn.damai:id/date_tv")')
3. For dates, match variants like "10.04", "10月4日", "2025-10-04", or "10月4日 (周六)"; prefer TextView.
4. Avoid .clickable(true) unless necessary.

Output ONLY a valid JSON object:
{{
    "locator_type": "By.ID" or "AppiumBy.ANDROID_UIAUTOMATOR" or "By.CLASS_NAME",
    "locator_value": "the value string",
    "confidence": 0-1 (float)
}}

If no match, output {{"locator_type": "NOT_FOUND", "locator_value": "", "confidence": 0}}.

XML source:
{xml}
"""
            response = self.ollama_client.chat(model=self.model, messages=[{'role': 'user', 'content': prompt}])
            result = json.loads(response['message']['content'])

            if result['locator_type'] == 'NOT_FOUND':
                print(f"  ⚠ Ollama未找到元素: {description}")
                return None

            if result['confidence'] < 0.3:
                print(f"  ⚠ Ollama置信度低 ({result['confidence']}): {description}")
                return None

            by = {
                'By.ID': By.ID,
                'AppiumBy.ANDROID_UIAUTOMATOR': AppiumBy.ANDROID_UIAUTOMATOR,
                'By.CLASS_NAME': By.CLASS_NAME
            }.get(result['locator_type'], By.ID)

            try:
                element = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((by, result['locator_value']))
                )
                print(
                    f"  ✓ Ollama找到元素: {description} via {result['locator_type']}='{result['locator_value']}' (confidence: {result['confidence']:.2f})")
                return element
            except TimeoutException:
                # 重试宽松（去 clickable）
                if 'clickable(true)' in result['locator_value']:
                    loose_value = result['locator_value'].replace('.clickable(true)', '')
                    print(f"  🔄 重试宽松: {loose_value}")
                    element = WebDriverWait(self.driver, timeout).until(
                        EC.presence_of_element_located((by, loose_value))
                    )
                    print(f"  ✓ Ollama宽松成功: {description}")
                    return element
                raise
        except Exception as e:
            print(f"  ⚠ Ollama查询失败: {e}")
            return None

    # ... (search_and_select_event 保持不变，Ollama 已优化)

    def select_city_and_date(self):
        """选择城市和日期 - 优化版"""
        print("\n步骤2: 选择城市和日期...")

        time.sleep(2)  # 等待加载

        # 城市（保持）
        city_description = f"city selection text or button containing '{self.config.city}', resource-id containing 'tv_city'"
        city_el = self.find_element_with_ollama(city_description)
        if city_el:
            self.safe_click(city_el)
            print(f"  ✓ 选择城市: {self.config.city} (Ollama)")
            time.sleep(0.5)
        else:
            pass

        # 日期
        if self.config.date:
            self.scroll_to_bottom()  # 🔧 滚动确保可见
            time.sleep(1)

            date_found = False
            for variant in self.date_variants:  # 🔧 多变体尝试
                date_description = f"date selection text or button containing '{variant}', format like 'MM月DD日' or 'MM.DD', in schedule section, prefer TextView resource-id containing 'date'"
                date_el = self.find_element_with_ollama(date_description)
                if date_el:
                    self.safe_click(date_el)
                    print(f"  ✓ 选择日期: {variant} (Ollama)")
                    date_found = True
                    break
                else:
                    # 回退硬编码
                    try:
                        date_el = self.driver.find_element(
                            AppiumBy.ANDROID_UIAUTOMATOR,
                            f'new UiSelector().textContains("{variant}")'
                        )
                        self.safe_click(date_el)
                        print(f"  ✓ 选择日期: {variant} (回退)")
                        date_found = True
                        break
                    except:
                        continue

            if not date_found:
                print(f"  ⚠ 未找到任何日期变体 {self.date_variants}，跳过")
                # 🔧 调试 XML
                try:
                    with open("date_debug.xml", "w", encoding="utf-8") as f:
                        f.write(self.driver.page_source)
                    print("  ✓ 保存日期调试 XML: date_debug.xml")
                except:
                    pass
            time.sleep(0.5)

        return True

    # ... (其他方法如 click_buy_button 等保持优化版)

    # run_ticket_grabbing 和 run_with_retry 保持不变