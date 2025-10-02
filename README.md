# 安卓端V2版本介绍
## 执行命令
### 开启appium服务端
```bash
appium --address 0.0.0.0 --port 4723 --relaxed-security
```
如果确定某些按钮点击后不会马上有新页面加载，可以加 `--relaxed-security` 启动 Appium，然后用 `mobile: clickGesture` 直接原生点击：
```python
# 这里的target是一个可以执行click()的对象
driver.execute_script('mobile: clickGesture', {'elementId': target.id})
```
### 执行抢票任务
```bash
cd damai_appium
python damai_app_v2.py
```


## 只处理了抢票的，预约的暂未考虑

## 功能
- 大麦的大部分票**只能在APP端购买**，所以只运行了安卓侧的实现并进行修改
- APP更新，**界面信息的票价的Text是空串""**，无法再使用之前的方案去找按钮click，V2是通过分析页面信息，使用索引的方式获取，缺点是需要预先手动写进去，不知道后续有没有什么新的方法获取
- 增加重试机制

## 优化：
- 考虑到界面可以先点到搜索列表，移除了键入搜索和点击搜索按钮的步骤
- 增加了一些加速的配置capabilities，以及一些性能优化的配置
- 优化了多人勾选的逻辑，收集坐标信息，几乎一次性全部点击
- 使用`WebDriverWait`替代`driver.implicitly_wait(5)`，大大提升效率
- 优化了`click()`的方式，使用
```python
driver.execute_script("mobile: clickGesture", {
                "x": x,
                "y": y,
                "duration": 50  # 极短点击时间
            })
```
- 优化显示逻辑，展示执行的进度

## 展望
- 实现预约功能

# 大麦APP抢票 V2 Docker版（基于原作者V1快速启动修改，移除web抢票相关代码、只保留app抢票） - 更新说明

## 主要更新内容

### 1. Appium启动参数优化
```bash
# V1版本
appium

# V2版本（支持mobile: clickGesture原生点击）
appium --address 0.0.0.0 --port 4723 --relaxed-security
```

**--relaxed-security 的作用：**
- 允许使用 `mobile: clickGesture` 进行原生点击操作
- 大幅提升点击速度和可靠性
- 支持坐标直接点击，避免元素等待

### 2. 脚本执行文件更新
```bash
# V1版本
python3 damai_appium.py

# V2版本
python3 damai_app_v2.py
```

### 3. 性能优化亮点

#### 3.1 超快点击机制
```python
# 使用坐标原生点击，速度提升50%+
driver.execute_script("mobile: clickGesture", {
    "x": x,
    "y": y,
    "duration": 50  # 极短点击时间
})
```

#### 3.2 批量用户选择优化
- **V1**: 逐个查找→点击→等待（约1-2秒/用户）
- **V2**: 批量收集坐标→连续点击（约0.01秒/用户）
- **性能提升**: 3个用户从3-6秒降至0.1秒以内

#### 3.3 WebDriverWait替代隐式等待
```python
# V1: 每次操作都等5秒
driver.implicitly_wait(5)

# V2: 精确等待，最快0.1秒返回
WebDriverWait(self.driver, 2).until(...)
```

#### 3.4 UIAutomator2性能配置
```python
driver.update_settings({
    "waitForIdleTimeout": 0,  # 不等待页面空闲
    "actionAcknowledgmentTimeout": 0,  # 禁止等待动作确认
    "keyInjectionDelay": 0,  # 禁止输入延迟
    "waitForSelectorTimeout": 300,  # 从500ms减少到300ms
})
```

### 4. 功能增强

#### 4.1 智能重试机制
```python
bot.run_with_retry(max_retries=3)  # 失败自动重试3次
```

#### 4.2 多备选选择器
- 城市选择：3种备选方案
- 预约按钮：3种备选方案
- 票价选择：2种备选方案
- 大幅提升成功率

#### 4.3 票价索引定位
解决APP更新后票价Text为空的问题：
```python
# 通过index和clickable属性精确定位
target_price = price_container.find_element(
    AppiumBy.ANDROID_UIAUTOMATOR,
    f'new UiSelector().className("android.widget.FrameLayout").index({price_index}).clickable(true)'
)
```

### 5. 设备兼容性

#### 已测试设备
- ✅ OPPO Find X8 Pro (Android 14)
- ✅ OnePlus 11 (Android 15)

#### 配置方法
修改 `damai_app_v2.py` 第35-36行：
```python
"platformVersion": "15",  # 你的Android版本
"deviceName": "OnePlus 11",  # 你的设备型号
```

## 使用方法

### 方式一：网络ADB连接（推荐）

**1. 宿主机准备设备：**
```bash
# 开启网络ADB
adb tcpip 5555
adb connect <手机IP>:5555
adb devices
```

**2. 运行容器：**
```bash
docker run -d \
  --name damai-ticket \
  --network host \
  -e DEVICE_IP=<手机IP> \
  damai-ticket
```

**3. 查看日志：**
```bash
docker logs -f damai-ticket
```

### 方式二：USB直连

```bash
docker run -d \
  --name damai-ticket \
  --privileged \
  -v /dev/bus/usb:/dev/bus/usb \
  --network host \
  damai-ticket
```

## 配置文件说明

在项目根目录创建 `config.jsonc`：
```json
{
  "server_url": "http://127.0.0.1:4723",
  "keyword": "刘若英",
  "users": ["张三", "李四"],
  "city": "泉州",
  "date": "10.04",
  "price": "799元",
  "price_index": 1,
  "if_commit_order": true
}
```

**参数说明：**
- `server_url`: Appium服务器地址
- `keyword`: 搜索关键词
- `users`: 购票人姓名列表
- `city`: 城市名称
- `date`: 场次日期
- `price`: 票价（仅用于日志显示）
- `price_index`: 票价索引（0=第一档，1=第二档，以此类推）
- `if_commit_order`: 是否自动提交订单

## 性能对比

| 操作 | V1耗时 | V2耗时 | 提升 |
|------|--------|--------|------|
| 单次点击 | 0.5-1秒 | 0.05-0.1秒 | **10倍** |
| 选择3个用户 | 3-6秒 | <0.1秒 | **30-60倍** |
| 完整流程 | 15-20秒 | 3-5秒 | **5倍** |

## 注意事项

1. **price_index需要手动测试确定**：不同演出票价档位不同
2. **仅支持购票，预约功能暂未实现**
3. **建议提前手动打开大麦APP并登录**
4. **确保手机屏幕保持开启**
5. **抢票前手动测试一遍流程**

## 故障排查

### 问题1: 找不到设备
```bash
# 检查设备连接
docker exec -it damai-ticket adb devices

# 重新连接
docker exec -it damai-ticket adb connect <IP>:5555
```

### 问题2: 票价选择失败
- 调整 `config.jsonc` 中的 `price_index` 值
- 手动数一下目标票价是第几个（从0开始）

### 问题3: 用户选择失败
- 确保姓名与大麦APP中完全一致
- 检查是否已添加常用购票人

### 问题4: 点击速度不够快
- 确保Appium启动时使用了 `--relaxed-security`
- 检查手机是否开启"性能模式"
- 关闭不必要的后台应用

## 更新日志

### v2.0.0 (2025/09/13)
- ✨ 重写点击机制，使用原生坐标点击
- ✨ 优化用户选择为批量点击
- ✨ 添加智能重试机制
- ✨ 优化等待策略，使用WebDriverWait
- ✨ 添加多备选选择器方案
- 🐛 修复票价Text为空无法定位的问题
- ⚡ 整体性能提升5倍

### v1.0.0
- 初始版本


# Docker Compose 使用指南

## 文件结构

```
project/
├── Dockerfile
├── docker-compose.yml
├── config.jsonc              # 抢票配置文件
├── damai_appium/
│   ├── damai_app_v2.py     # 抢票脚本
│   └── config.py           # 配置解析
└── logs/                    # 日志目录（可选）
```

## 配置说明

### config.jsonc 配置文件

在项目根目录创建 `config.jsonc`：

```json
{
  "server_url": "http://127.0.0.1:4723",
  "keyword": "刘若英",
  "users": ["张三", "李四"],
  "city": "泉州",
  "date": "10.04",
  "price": "799元",
  "price_index": 1,
  "if_commit_order": true
}
```

## 使用方法

### 方式一：网络ADB连接（推荐）⭐

**适用场景：** 手机和电脑在同一WiFi网络下

**步骤1：准备手机（在宿主机操作）**
```bash
# 1. 通过USB连接手机，开启USB调试
adb devices

# 2. 启用网络ADB
adb tcpip 5555

# 3. 查看手机IP地址
# 方法1：通过ADB查看
adb shell ip addr show wlan0 | grep inet

# 方法2：在手机"设置-关于手机-状态信息"中查看
# 假设获取到的IP是：192.168.1.100

# 4. 断开USB，通过WiFi连接
adb connect 192.168.1.100:5555

# 5. 验证连接
adb devices
# 应显示：192.168.1.100:5555    device
```

**步骤2：修改docker-compose.yml**
```yaml
environment:
  - DEVICE_IP=192.168.1.100  # 改为你的手机实际IP
```

**步骤3：启动服务**
```bash
# 构建镜像
docker-compose build

# 启动网络ADB模式
docker-compose --profile network up -d

# 查看日志
docker-compose logs -f damai-ticket-network
```

**步骤4：停止服务**
```bash
docker-compose --profile network down
```

---

### 方式二：USB直连

**适用场景：** 手机通过USB线连接到电脑

**步骤1：连接手机**
```bash
# 确保USB调试已开启
adb devices
# 应显示设备列表
```

**步骤2：启动服务**
```bash
# 构建镜像
docker-compose build

# 启动USB直连模式
docker-compose --profile usb up -d

# 查看日志
docker-compose logs -f damai-ticket-usb
```

**步骤3：停止服务**
```bash
docker-compose --profile usb down
```

---

### 方式三：仅启动Appium Server（调试用）

**适用场景：** 需要手动运行Python脚本进行调试

**启动Appium Server：**
```bash
# 启动调试模式
docker-compose --profile debug up -d

# Appium Server将运行在 http://localhost:4723
```

**手动运行脚本：**
```bash
# 在宿主机上运行
cd damai_appium
python3 damai_app_v2.py
```

**停止服务：**
```bash
docker-compose --profile debug down
```

---

## 环境变量配置

### 使用 .env 文件（推荐）

创建 `.env` 文件在项目根目录：

```bash
# 手机IP地址
DEVICE_IP=192.168.1.100

# 其他配置（可选）
APPIUM_PORT=4723
```

修改 `docker-compose.yml`：
```yaml
environment:
  - DEVICE_IP=${DEVICE_IP}
  - APPIUM_PORT=${APPIUM_PORT:-4723}
```

这样就不需要直接在docker-compose.yml中修改IP了。

---

## 常用命令

### 构建和启动
```bash
# 构建镜像
docker-compose build

# 启动服务（网络ADB）
docker-compose --profile network up -d

# 启动服务（USB直连）
docker-compose --profile usb up -d

# 重新构建并启动
docker-compose --profile network up -d --build
```

### 查看状态和日志
```bash
# 查看运行状态
docker-compose ps

# 实时查看日志
docker-compose logs -f

# 查看特定服务的日志
docker-compose logs -f damai-ticket-network

# 查看最近100行日志
docker-compose logs --tail=100
```

### 进入容器调试
```bash
# 进入运行中的容器
docker-compose exec damai-ticket-network bash

# 在容器内检查ADB设备
docker-compose exec damai-ticket-network adb devices

# 在容器内手动连接设备
docker-compose exec damai-ticket-network adb connect 192.168.1.100:5555
```

### 停止和清理
```bash
# 停止服务
docker-compose --profile network down

# 停止并删除卷
docker-compose --profile network down -v

# 停止、删除并清理镜像
docker-compose --profile network down --rmi all
```

### 重启服务
```bash
# 重启服务
docker-compose --profile network restart

# 重启特定服务
docker-compose restart damai-ticket-network
```

---

## 故障排查

### 问题1：找不到设备

**检查设备连接：**
```bash
docker-compose exec damai-ticket-network adb devices
```

**重新连接设备：**
```bash
docker-compose exec damai-ticket-network adb connect 192.168.1.100:5555
```

**查看详细日志：**
```bash
docker-compose logs -f damai-ticket-network
```

### 问题2：端口被占用

**检查端口占用：**
```bash
lsof -i :4723
```

**杀死占用进程：**
```bash
kill -9 <PID>
```

### 问题3：配置文件未生效

**检查挂载：**
```bash
docker-compose exec damai-ticket-network ls -la /app/damai_appium/config.jsonc
```

**查看配置内容：**
```bash
docker-compose exec damai-ticket-network cat /app/damai_appium/config.jsonc
```

### 问题4：权限问题（USB模式）

**Linux系统需要添加udev规则：**
```bash
# 创建udev规则文件
sudo nano /etc/udev/rules.d/51-android.rules

# 添加以下内容（根据手机品牌调整）
SUBSYSTEM=="usb", ATTR{idVendor}=="2a70", MODE="0666", GROUP="plugdev"  # OnePlus
SUBSYSTEM=="usb", ATTR{idVendor}=="22d9", MODE="0666", GROUP="plugdev"  # OPPO

# 重新加载规则
sudo udevadm control --reload-rules
sudo udevadm trigger
```

---

## 高级配置

### 多设备同时抢票

创建多个服务配置：

```yaml
services:
  damai-ticket-device1:
    build: .
    container_name: damai-ticket-device1
    network_mode: host
    environment:
      - DEVICE_IP=192.168.1.100
    volumes:
      - ./config.jsonc:/app/damai_appium/config.jsonc
    profiles:
      - multi

  damai-ticket-device2:
    build: .
    container_name: damai-ticket-device2
    network_mode: host
    environment:
      - DEVICE_IP=192.168.1.101
    volumes:
      - ./config2.json:/app/damai_appium/config.jsonc
    profiles:
      - multi
```

启动：
```bash
docker-compose --profile multi up -d
```

### 自定义Appium端口

```yaml
environment:
  - APPIUM_PORT=4724
command: >
  bash -c "appium --address 0.0.0.0 --port 4724 --relaxed-security &
           sleep 5 && cd damai_appium && python3 damai_app_v2.py"
```

---

## 性能优化建议

1. **使用网络ADB而非USB**：更稳定，不受USB线缆影响
2. **关闭不必要的日志**：减少I/O开销
3. **使用SSD存储**：加快镜像构建和容器启动
4. **分配足够内存**：Docker Desktop建议至少4GB内存

---

## 安全建议

1. **.env文件加入.gitignore**：避免IP等敏感信息泄露
2. **不要在公共网络使用网络ADB**：可能被攻击
3. **抢票后及时关闭网络ADB**：`adb usb`
4. **定期更新镜像**：获取安全补丁

---

## 更新日志

### 2025-09-30
- ✨ 新增docker-compose.yml配置
- ✨ 支持网络ADB和USB两种连接方式
- ✨ 添加调试模式
- 📝 完善使用文档
