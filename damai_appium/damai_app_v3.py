# -*- coding: UTF-8 -*-
"""
__Author__ = "BlueCestbon"
__Version__ = "2.3.2"
__Description__ = "大麦app抢票自动化 - Ollama优化版"
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

        # 优化的设置
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

    def scroll_to_date(self):
        """滚动查找日期（新增）"""
        print("  📜 滚动查找日期...")
        try:
            size = self.driver.get_window_size()
            for _ in range(3):
                self.driver.execute_script('mobile: scrollGesture', {
                    'left': 100, 'top': 500, 'width': 800, 'height': 1500,
                    'direction': 'down', 'percent': 0.5
                })
                time.sleep(0.5)
            print("  ✓ 已滚动到底部")
        except Exception as e:
            print(f"  ⚠ 滚动失败: {e}")

    def find_element_with_ollama(self, description, timeout=5):
        """使用Ollama分析XML，查找元素locator（优化版）"""
        try:
            xml = self.driver.page_source[:15000]  # 增加截断长度
            # 🔧 优化 prompt：更具体，指定变体，优先 TextView
            prompt = f"""
You are an expert in Appium automation for Android apps. Analyze the following Appium XML page source and identify the best locator for the UI element described: "{description}".

Focus on visible, clickable elements. Prioritize:
1. By.ID with full resource-id (e.g., "cn.damai:id/btn_buy")
2. AppiumBy.ANDROID_UIAUTOMATOR with text, textContains, or resourceId (e.g., 'new UiSelector().textContains("10.04").resourceId("cn.damai:id/date_tv")')
3. For dates, match formats like "10.04", "10月4日", or "2025-10-04"; prefer TextView even if not clickable.
4. By.CLASS_NAME if needed.

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

            if result['confidence'] < 0.3:  # 🔧 降低阈值
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
                # 🔧 新增：超时重试宽松版（去 clickable）
                if 'clickable(true)' in result['locator_value']:
                    loose_value = result['locator_value'].replace('.clickable(true)', '')
                    print(f"  🔄 Ollama重试宽松 locator: {loose_value}")
                    element = WebDriverWait(self.driver, timeout).until(
                        EC.presence_of_element_located((by, loose_value))
                    )
                    print(f"  ✓ Ollama宽松成功: {description}")
                    return element
                raise
        except json.JSONDecodeError as e:
            print(f"  ⚠ Ollama JSON解析失败: {e}")
            return None
        except Exception as e:
            print(f"  ⚠ Ollama查询失败: {e}")
            return None

    def search_and_select_event(self):
        """搜索并选择演出 - 强化版"""
        print("\n步骤1: 搜索演出...")

        # 等待首页加载
        time.sleep(2)

        # 使用Ollama查找搜索按钮
        search_element = self.find_element_with_ollama(
            "search icon or button in the app header, likely a magnifying glass or search text, resource-id containing 'search'")
        if search_element:
            self.safe_click(search_element)
            print("  ✓ 点击搜索区域 (Ollama)")
        else:
            # 回退原逻辑
            try:
                search_area = self.driver.find_element(
                    By.ID, "cn.damai:id/homepage_header_search"
                )
                self.safe_click(search_area)
                print("  ✓ 点击搜索区域")
            except:
                try:
                    search_btn = self.driver.find_element(
                        By.ID, "cn.damai:id/homepage_header_search_btn"
                    )
                    self.safe_click(search_btn)
                    print("  ✓ 点击搜索按钮")
                except:
                    print("  ✗ 无法打开搜索")
                    self.quick_screenshot("search_failed")
                    return False
        time.sleep(0.5)

        # 使用Ollama查找输入框
        input_element = self.find_element_with_ollama(
            "search input field, EditText for typing keywords, resource-id containing 'input' or 'edit'")
        if input_element:
            input_element.clear()
            input_element.send_keys(self.config.keyword)
            print(f"  ✓ 输入关键词: {self.config.keyword} (Ollama)")
        else:
            # 回退原逻辑
            input_found = False
            input_selectors = [
                (By.CLASS_NAME, "android.widget.EditText"),
                (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().className("android.widget.EditText")'),
            ]

            for by, value in input_selectors:
                try:
                    input_box = WebDriverWait(self.driver, 2).until(
                        EC.presence_of_element_located((by, value))
                    )
                    input_box.clear()
                    input_box.send_keys(self.config.keyword)
                    print(f"  ✓ 输入关键词: {self.config.keyword}")
                    input_found = True
                    break
                except:
                    continue

            if not input_found:
                print("  ✗ 未找到输入框")
                self.quick_screenshot("input_not_found")
                return False

        # 【关键修复】直接按Enter键触发搜索，避免空格问题
        print("  按Enter触发搜索...")
        try:
            self.driver.press_keycode(66)  # Android keycode 66 = ENTER
            time.sleep(1.5)
            print("  ✓ 已触发搜索")
        except Exception as e:
            print(f"  ⚠ Enter键失败: {e}")
            time.sleep(1.5)

        # 使用Ollama查找第一个搜索结果
        result_element = self.find_element_with_ollama(
            "first clickable search result item in the list, likely a RecyclerView child with text matching keyword, resource-id containing 'tv_word' or 'title'")
        if result_element:
            self.safe_click(result_element)
            print("  ✓ 点击第一个搜索结果 (Ollama)")
        else:
            # 回退原逻辑
            try:
                # 等待搜索结果加载
                time.sleep(1)

                # 查找RecyclerView（搜索结果通常在这里）
                result_list = self.driver.find_element(
                    By.CLASS_NAME, "androidx.recyclerview.widget.RecyclerView"
                )

                # 获取第一个可点击的子元素
                first_result = result_list.find_element(
                    AppiumBy.ANDROID_UIAUTOMATOR,
                    'new UiSelector().clickable(true).index(0)'
                )

                self.safe_click(first_result)
                print("  ✓ 点击第一个搜索结果")
                time.sleep(1.5)
                return True

            except Exception as e:
                print(f"  ⚠ 方式1失败: {e}")

            # 【方式2】通过坐标点击（假设搜索结果在屏幕上半部分）
            print("  尝试通过坐标点击...")
            try:
                # 获取屏幕尺寸
                size = self.driver.get_window_size()
                width = size['width']
                height = size['height']

                # 点击屏幕上部中间位置（通常是第一个搜索结果）
                x = width // 2
                y = height // 4

                self.driver.execute_script("mobile: clickGesture", {
                    "x": x, "y": y, "duration": 50
                })
                print(f"  ✓ 坐标点击: ({x}, {y})")
                time.sleep(1.5)
                return True

            except Exception as e:
                print(f"  ⚠ 方式2失败: {e}")

            # 【方式3】查找任意可点击的TextView（宽松匹配）
            print("  尝试查找可点击TextView...")
            try:
                textviews = self.driver.find_elements(
                    AppiumBy.ANDROID_UIAUTOMATOR,
                    'new UiSelector().className("android.widget.TextView").clickable(true)'
                )

                # 点击第一个非空文本的TextView
                for tv in textviews[:5]:  # 只检查前5个
                    text = tv.text
                    if text and len(text) > 0:
                        self.safe_click(tv)
                        print(f"  ✓ 点击TextView: {text}")
                        time.sleep(1.5)
                        return True

            except Exception as e:
                print(f"  ⚠ 方式3失败: {e}")

        time.sleep(1.5)
        return True

    def select_city_and_date(self):
        """选择城市和日期 - 简化版"""
        print("\n步骤2: 选择城市和日期...")

        # 🔧 新增：等待页面加载
        time.sleep(2)

        # 使用Ollama查找城市元素
        city_description = f"city selection text or button containing '{self.config.city}', in header or filter section"
        city_el = self.find_element_with_ollama(city_description)
        if city_el:
            self.safe_click(city_el)
            print(f"  ✓ 选择城市: {self.config.city} (Ollama)")
        else:
            # 回退原逻辑
            try:
                city_el = WebDriverWait(self.driver, 2).until(
                    EC.presence_of_element_located((
                        AppiumBy.ANDROID_UIAUTOMATOR,
                        f'new UiSelector().textContains("{self.config.city}")'
                    ))
                )
                self.safe_click(city_el)
                print(f"  ✓ 选择城市: {self.config.city}")
                time.sleep(0.5)
            except:
                # 尝试滚动查找
                for _ in range(2):
                    try:
                        city_el = self.driver.find_element(
                            AppiumBy.ANDROID_UIAUTOMATOR,
                            f'new UiSelector().textContains("{self.config.city}")'
                        )
                        self.safe_click(city_el)
                        print(f"  ✓ 滚动后选择城市: {self.config.city}")
                        time.sleep(0.5)
                        break
                    except:
                        self.driver.execute_script('mobile: scrollGesture', {
                            'left': 100, 'top': 500, 'width': 800, 'height': 1500,
                            'direction': 'down', 'percent': 0.5
                        })
                        time.sleep(0.3)
                else:
                    print(f"  ⚠ 未找到城市，继续")
        time.sleep(0.5)

        # 日期选择（可选）
        # if self.config.date:
        #     # 🔧 新增：滚动确保日期可见
        #     self.scroll_to_date()
        #     time.sleep(1)
        #
        #     date_description = f"date selection text or button containing '{self.config.date}', format like '10.04' or '10月4日', in schedule or calendar section, prefer TextView"
        #     date_el = self.find_element_with_ollama(date_description)
        #     if date_el:
        #         self.safe_click(date_el)
        #         print(f"  ✓ 选择日期: {self.config.date} (Ollama)")
        #     else:
        #         # 回退原逻辑 + 调试
        #         try:
        #             date_el = self.driver.find_element(
        #                 AppiumBy.ANDROID_UIAUTOMATOR,
        #                 f'new UiSelector().textContains("{self.config.date}")'
        #             )
        #             self.safe_click(date_el)
        #             print(f"  ✓ 选择日期: {self.config.date}")
        #             time.sleep(0.5)
        #         except:
        #             # 🔧 新增：尝试中文格式
        #             try:
        #                 chinese_date = self.config.date.replace('.', '月') + '日'
        #                 date_el = self.driver.find_element(
        #                     AppiumBy.ANDROID_UIAUTOMATOR,
        #                     f'new UiSelector().textContains("{chinese_date}")'
        #                 )
        #                 self.safe_click(date_el)
        #                 print(f"  ✓ 选择日期: {chinese_date} (中文格式)")
        #                 time.sleep(0.5)
        #             except:
        #                 print(f"  ⚠ 未找到日期 '{self.config.date}'，跳过（可能需手动检查场次）")
        #                 # 🔧 新增：调试打印 XML
        #                 try:
        #                     with open("date_debug.xml", "w", encoding="utf-8") as f:
        #                         f.write(self.driver.page_source)
        #                     print("  ✓ 已保存日期调试 XML: date_debug.xml")
        #                 except:
        #                     pass
        #     time.sleep(0.5)

        return True

    def click_buy_button(self):
        """点击购买按钮"""
        print("\n步骤3: 点击购买...")

        # 🔧 新增：等待详情页加载 + 关闭弹窗
        time.sleep(3)
        self.close_popups() if hasattr(self, 'close_popups') else None

        # 使用Ollama查找购买按钮
        buy_description = "bottom fixed buy ticket button, likely with text '立即购票' or '购买' or '选座购买' or similar purchase action, in status bar or footer, resource-id containing 'buy' or 'purchase'"
        btn = self.find_element_with_ollama(buy_description)
        if btn:
            self.safe_click(btn)
            print("  ✓ 购买按钮已点击 (Ollama)")
            time.sleep(1)
            return True
        else:
            # 回退原逻辑 + 新备选
            buy_ids = [
                "cn.damai:id/trade_project_detail_purchase_status_bar_container_fl",
                "cn.damai:id/btn_buy",
                "cn.damai:id/btn_select_seat_buy",  # 🔧 新增：选座购买
            ]

            # 先尝试ID
            for buy_id in buy_ids:
                try:
                    btn = WebDriverWait(self.driver, 2).until(
                        EC.presence_of_element_located((By.ID, buy_id))
                    )
                    self.safe_click(btn)
                    print("  ✓ 购买按钮已点击")
                    time.sleep(1)
                    return True
                except:
                    continue

            # 再尝试文本（增强变体）
            try:
                btn = self.driver.find_element(
                    AppiumBy.ANDROID_UIAUTOMATOR,
                    'new UiSelector().textMatches(".*预约.*|.*购买.*|.*立即.*|.*选座.*")'
                )
                self.safe_click(btn)
                print("  ✓ 购买按钮已点击")
                time.sleep(1)
                return True
            except:
                # 🔧 新增：坐标回退（底部中央）
                try:
                    size = self.driver.get_window_size()
                    x = size['width'] // 2
                    y = int(size['height'] * 0.95)
                    self.driver.execute_script("mobile: clickGesture", {
                        "x": x, "y": y, "duration": 50
                    })
                    print(f"  ✓ 坐标点击购买: ({x}, {y})")
                    time.sleep(1)
                    return True
                except:
                    pass

            print("  ✗ 未找到购买按钮")
            self.quick_screenshot("buy_button_not_found")
            return False

    # ... (其他方法如 select_price, select_quantity 等保持不变)

    def select_price(self):
        """选择票价"""
        print("\n步骤4: 选择票价...")

        # 使用Ollama查找价格容器
        container = self.find_element_with_ollama(
            "price selection container FlowLayout for ticket prices, resource-id containing 'price_flowlayout'")
        if container:
            time.sleep(0.3)
            # 使用Ollama查找目标价格（相对索引）
            price_desc = f"the {self.config.price_index + 1}th clickable price option in the container, FrameLayout with price text"
            target_price = self.find_element_with_ollama(price_desc)
            if target_price:
                self.safe_click(target_price)
                print(f"  ✓ 票价已选择 (index: {self.config.price_index}) (Ollama)")
                time.sleep(0.3)
                return True
        else:
            # 回退原逻辑
            try:
                price_container = WebDriverWait(self.driver, 3).until(
                    EC.presence_of_element_located((
                        By.ID, 'cn.damai:id/project_detail_perform_price_flowlayout'
                    ))
                )
                time.sleep(0.3)

                target_price = price_container.find_element(
                    AppiumBy.ANDROID_UIAUTOMATOR,
                    f'new UiSelector().className("android.widget.FrameLayout").index({self.config.price_index})'
                )
                self.safe_click(target_price)
                print(f"  ✓ 票价已选择 (index: {self.config.price_index})")
                time.sleep(0.3)
                return True
            except:
                pass

        print(f"  ✗ 票价选择失败")
        self.quick_screenshot("price_selection_failed")
        return False

    def select_quantity(self):
        """选择数量"""
        print("\n步骤5: 选择数量...")

        clicks_needed = len(self.config.users) - 1
        if clicks_needed <= 0:
            print(f"  ⚠ 只需1张票，跳过")
            return True

        # 使用Ollama查找+按钮
        plus_button = self.find_element_with_ollama(
            "plus (+) button to increase ticket quantity, resource-id containing 'jia' or icon")
        if plus_button:
            for _ in range(clicks_needed):
                self.safe_click(plus_button)
                time.sleep(0.05)
            print(f"  ✓ 数量: {len(self.config.users)} (Ollama)")
            return True
        else:
            # 回退原逻辑
            try:
                plus_button = self.driver.find_element(By.ID, 'img_jia')
                for _ in range(clicks_needed):
                    self.safe_click(plus_button)
                    time.sleep(0.05)
                print(f"  ✓ 数量: {len(self.config.users)}")
                return True
            except:
                pass

        print(f"  ⚠ 未找到数量选择器")
        return True  # 不影响流程

    def confirm_purchase(self):
        """确认购买"""
        print("\n步骤6: 确认购买...")

        # 使用Ollama查找确认按钮
        confirm_desc = "confirm purchase button, likely with text '确定' or '购买' or '提交订单', resource-id containing 'buy_view'"
        confirm_btn = self.find_element_with_ollama(confirm_desc)
        if confirm_btn:
            self.safe_click(confirm_btn)
            print("  ✓ 确认按钮已点击 (Ollama)")
            time.sleep(0.8)
            return True
        else:
            # 回退原逻辑
            try:
                confirm_btn = WebDriverWait(self.driver, 2).until(
                    EC.presence_of_element_located((By.ID, "btn_buy_view"))
                )
                self.safe_click(confirm_btn)
                print("  ✓ 确认按钮已点击")
                time.sleep(0.8)
                return True
            except:
                # 尝试文本查找
                try:
                    confirm_btn = self.driver.find_element(
                        AppiumBy.ANDROID_UIAUTOMATOR,
                        'new UiSelector().textMatches(".*确定.*|.*购买.*")'
                    )
                    self.safe_click(confirm_btn)
                    print("  ✓ 确认按钮已点击")
                    time.sleep(0.8)
                    return True
                except:
                    pass

        print("  ✗ 未找到确认按钮")
        return False

    def select_users(self):
        """选择购票人"""
        print("\n步骤7: 选择购票人...")

        success = False
        for i, user in enumerate(self.config.users):
            user_desc = f"buyer user selection item containing name '{user}', in list or checkbox"
            user_el = self.find_element_with_ollama(user_desc)
            if user_el:
                self.safe_click(user_el)
                print(f"  ✓ 已选择: {user} (Ollama)")
                success = True
                time.sleep(0.1)
            else:
                # 回退原逻辑
                try:
                    user_el = WebDriverWait(self.driver, 1.5).until(
                        EC.presence_of_element_located((
                            AppiumBy.ANDROID_UIAUTOMATOR,
                            f'new UiSelector().textContains("{user}")'
                        ))
                    )
                    self.safe_click(user_el)
                    print(f"  ✓ 已选择: {user}")
                    success = True
                    time.sleep(0.1)
                except:
                    print(f"  ✗ 未找到用户: {user}")

        return success

    def submit_order(self):
        """提交订单"""
        print("\n步骤8: 提交订单...")

        if not self.config.if_commit_order:
            print("  ⚠ 配置为不提交，跳过")
            return True

        # 使用Ollama查找提交按钮
        submit_desc = "submit order button with text '立即提交' or '支付' or similar, at bottom"
        submit_btn = self.find_element_with_ollama(submit_desc)
        if submit_btn:
            self.safe_click(submit_btn)
            print("  ✓ 订单已提交 (Ollama)")
            return True
        else:
            # 回退原逻辑
            try:
                submit_btn = WebDriverWait(self.driver, 2).until(
                    EC.presence_of_element_located((
                        AppiumBy.ANDROID_UIAUTOMATOR,
                        'new UiSelector().text("立即提交")'
                    ))
                )
                self.safe_click(submit_btn)
                print("  ✓ 订单已提交")
                return True
            except:
                pass

        print("  ✗ 提交失败")
        self.quick_screenshot("submit_failed")
        return False

    def run_ticket_grabbing(self):
        """执行抢票流程"""
        try:
            print("\n" + "=" * 60)
            print("开始抢票流程")
            print("=" * 60)
            start_time = time.time()

            steps = [
                ("搜索演出", self.search_and_select_event),
                ("选择城市日期", self.select_city_and_date),
                ("点击购买", self.click_buy_button),
                ("选择票价", self.select_price),
                ("选择数量", self.select_quantity),
                ("确认购买", self.confirm_purchase),
                ("选择用户", self.select_users),
                ("提交订单", self.submit_order),
            ]

            for step_name, step_func in steps:
                if not step_func():
                    print(f"\n✗ 失败于: {step_name}")
                    return False
                time.sleep(1)  # 🔧 新增：步骤间等待

            elapsed = time.time() - start_time
            print("\n" + "=" * 60)
            print(f"✓ 流程完成！耗时: {elapsed:.1f}秒")
            print("=" * 60)
            return True

        except Exception as e:
            print(f"\n✗ 异常: {e}")
            self.quick_screenshot("exception")
            return False

    def run_with_retry(self, max_retries=3):
        """带重试的抢票"""
        for attempt in range(max_retries):
            print(f"\n{'=' * 60}")
            print(f"第 {attempt + 1}/{max_retries} 次尝试")
            print(f"{'=' * 60}")

            try:
                if self.run_ticket_grabbing():
                    print("\n🎉 抢票成功！")
                    return True
            except Exception as e:
                print(f"\n第 {attempt + 1} 次异常: {e}")

            if attempt < max_retries - 1:
                print(f"\n等待2秒后重试...")
                time.sleep(2)
                try:
                    self.driver.quit()
                except:
                    pass
                self._setup_driver()

        print("\n❌ 所有尝试失败")
        try:
            self.driver.quit()
        except:
            pass
        return False


if __name__ == "__main__":
    bot = DamaiBot()
    bot.run_with_retry(max_retries=3)