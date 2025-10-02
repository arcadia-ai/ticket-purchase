FROM ubuntu:22.04

# ========================================
# 镜像源配置说明（适配中国大陆网络环境）
# - Ubuntu APT: 阿里云镜像
# - npm: 淘宝镜像（npmmirror.com）
# - pip: 清华大学镜像
# - Android SDK: 腾讯云镜像（备用Google官方源）
# ========================================

# 设置环境变量避免交互式提示
ENV DEBIAN_FRONTEND=noninteractive

# 设置工作目录
WORKDIR /app

# 配置Ubuntu镜像源为阿里云镜像
RUN sed -i 's@//.*archive.ubuntu.com@//mirrors.aliyun.com@g' /etc/apt/sources.list && \
    sed -i 's/security.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list

# 安装基础依赖包
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    unzip \
    openjdk-11-jdk \
    python3 \
    python3-pip \
    git \
    usbutils \
    && rm -rf /var/lib/apt/lists/*

# 安装Python的ollama客户端库
RUN pip3 install ollama

# 安装Node.js 18.x（使用淘宝镜像下载二进制包）
# 注意：使用Node 18.20.2以获得更好的ES Module兼容性
ENV NODE_VERSION=18.20.2
RUN wget https://npmmirror.com/mirrors/node/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz -O /tmp/node.tar.xz && \
    tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 && \
    rm /tmp/node.tar.xz && \
    ln -s /usr/local/bin/node /usr/local/bin/nodejs

# 配置npm使用淘宝镜像源
RUN npm config set registry https://registry.npmmirror.com

# 验证Node.js和npm版本
RUN node -v && npm -v

# 设置环境变量跳过Chromedriver安装(避免安装错误)
ENV APPIUM_SKIP_CHROMEDRIVER_INSTALL=true

# 配置Android SDK环境变量
ENV ANDROID_HOME=/opt/android-sdk
ENV ANDROID_SDK_ROOT=/opt/android-sdk
ENV PATH="${PATH}:${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools"

# 下载并安装Android SDK Command Line Tools（使用国内镜像加速）
RUN mkdir -p ${ANDROID_HOME}/cmdline-tools && \
    wget -q https://mirrors.cloud.tencent.com/AndroidSDK/commandlinetools-linux-9477386_latest.zip -O /tmp/cmdline-tools.zip || \
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-9477386_latest.zip -O /tmp/cmdline-tools.zip && \
    unzip -q /tmp/cmdline-tools.zip -d ${ANDROID_HOME}/cmdline-tools && \
    mv ${ANDROID_HOME}/cmdline-tools/cmdline-tools ${ANDROID_HOME}/cmdline-tools/latest && \
    rm /tmp/cmdline-tools.zip

# 接受Android SDK许可协议
RUN yes | sdkmanager --licenses || true

# 只安装必要的Android SDK组件（最小化安装，节省空间）
# platform-tools: 包含adb等工具
# platforms;android-34: Android 14平台（兼容Android 15）
# build-tools;34.0.0: 对应的构建工具
RUN sdkmanager "platform-tools" \
    "platforms;android-34" \
    "build-tools;34.0.0" && \
    rm -rf /opt/android-sdk/temp/*

# 全局安装Appium Server（使用2.11.5稳定版本）
RUN npm install -g appium@2.11.5

# 全局安装UiAutomator2驱动（使用3.7.11稳定版本，避免ES Module兼容性问题）
RUN appium driver install uiautomator2@3.7.11

# 验证Appium安装
RUN appium -v

# 配置pip使用清华镜像源
RUN pip3 config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 安装Python的Appium客户端
RUN pip3 install --no-cache-dir appium-python-client

# 复制项目文件到容器
COPY . /app

# 暴露Appium Server默认端口
EXPOSE 4723

# 创建启动脚本（V2 版本 - 支持配置保存和重用）
RUN echo '#!/bin/bash\n\
CONFIG_FILE="/app/adb_config.txt"\n\
\n\
echo "========================================"\n\
echo "大麦抢票系统 V2 - Docker版（带Ollama支持）"\n\
echo "========================================"\n\
echo ""\n\
echo "启动 Appium Server（带 relaxed-security 支持）..."\n\
appium --address 0.0.0.0 --port 4723 --relaxed-security &\n\
APPIUM_PID=$!\n\
\n\
echo "等待 Appium Server 启动..."\n\
sleep 5\n\
\n\
# 函数：执行 ADB 连接\n\
connect_device() {\n\
  local mode=$1\n\
  local device_ip=$2\n\
  local pairing_port=$3\n\
  local pairing_code=$4\n\
  local connect_port=$5\n\
  local skip_pairing=$6  # 是否跳过配对（已配对过的设备）\n\
  \n\
  case $mode in\n\
    1)\n\
      # Android 11+ 无线调试模式\n\
      if [ "$skip_pairing" != "true" ]; then\n\
        echo ""\n\
        echo "开始配对..."\n\
        echo "设备 IP: $device_ip"\n\
        echo "配对端口: $pairing_port"\n\
        echo "连接端口: $connect_port"\n\
        echo ""\n\
        \n\
        # 执行配对\n\
        echo "$pairing_code" | adb pair $device_ip:$pairing_port\n\
        PAIR_RESULT=$?\n\
        \n\
        if [ $PAIR_RESULT -ne 0 ]; then\n\
          echo "❌ 配对失败！"\n\
          return 1\n\
        fi\n\
        \n\
        echo "✅ 配对成功！"\n\
        sleep 2\n\
      else\n\
        echo ""\n\
        echo "💡 跳过配对步骤（使用已保存的配对信息）"\n\
      fi\n\
      \n\
      echo ""\n\
      echo "正在连接设备 $device_ip:$connect_port ..."\n\
      adb connect $device_ip:$connect_port\n\
      \n\
      if [ $? -ne 0 ]; then\n\
        echo "❌ 连接失败！"\n\
        return 1\n\
      fi\n\
      \n\
      echo "✅ 连接成功！"\n\
      return 0\n\
      ;;\n\
      \n\
    2)\n\
      echo ""\n\
      echo "正在连接设备 $device_ip:$connect_port ..."\n\
      adb connect $device_ip:$connect_port\n\
      \n\
      if [ $? -ne 0 ]; then\n\
        echo "❌ 连接失败！"\n\
        return 1\n\
      fi\n\
      \n\
      echo "✅ 连接成功！"\n\
      return 0\n\
      ;;\n\
      \n\
    3)\n\
      echo ""\n\
      echo "使用 USB 连接的设备"\n\
      return 0\n\
      ;;\n\
  esac\n\
  return 1\n\
}\n\
\n\
# 函数：交互式配置\n\
interactive_config() {\n\
  echo ""\n\
  echo "========================================"\n\
  echo "ADB 无线连接配置"\n\
  echo "========================================"\n\
  echo ""\n\
  echo "请选择连接方式:"\n\
  echo "1) Android 11+ 无线调试（需要配对）"\n\
  echo "2) 传统 TCP/IP 模式（adb tcpip 5555）"\n\
  echo "3) 跳过网络连接（使用 USB 连接）"\n\
  echo ""\n\
  read -p "请输入选项 [1-3]: " CONNECTION_MODE\n\
  \n\
  case $CONNECTION_MODE in\n\
    1)\n\
      echo ""\n\
      echo "=== Android 11+ 无线调试模式 ==="\n\
      echo ""\n\
      echo "📱 请在手机上操作:"\n\
      echo "1. 进入「设置」→「开发者选项」→「无线调试」"\n\
      echo "2. 点击「使用配对码配对设备」"\n\
      echo "3. 记下弹窗中显示的信息"\n\
      echo ""\n\
      \n\
      read -p "请输入手机 IP 地址（例如: 192.168.1.100）: " DEVICE_IP\n\
      read -p "请输入配对端口（配对弹窗中显示的端口）: " ADB_PAIRING_PORT\n\
      read -p "请输入配对码（6位数字）: " ADB_PAIRING_CODE\n\
      read -p "请输入连接端口（无线调试主界面显示的端口，例如: 39885）: " ADB_CONNECT_PORT\n\
      \n\
      # 保存配置\n\
      echo "MODE=1" > $CONFIG_FILE\n\
      echo "DEVICE_IP=$DEVICE_IP" >> $CONFIG_FILE\n\
      echo "ADB_PAIRING_PORT=$ADB_PAIRING_PORT" >> $CONFIG_FILE\n\
      echo "ADB_PAIRING_CODE=$ADB_PAIRING_CODE" >> $CONFIG_FILE\n\
      echo "ADB_CONNECT_PORT=$ADB_CONNECT_PORT" >> $CONFIG_FILE\n\
      ;;\n\
      \n\
    2)\n\
      echo ""\n\
      echo "=== 传统 TCP/IP 模式 ==="\n\
      echo ""\n\
      echo "⚠️  前提条件: 你应该已经在手机上执行了 adb tcpip 5555"\n\
      echo ""\n\
      \n\
      read -p "请输入手机 IP 地址（例如: 192.168.1.100）: " DEVICE_IP\n\
      read -p "请输入连接端口 [默认: 5555]: " ADB_CONNECT_PORT\n\
      ADB_CONNECT_PORT=${ADB_CONNECT_PORT:-5555}\n\
      \n\
      # 保存配置\n\
      echo "MODE=2" > $CONFIG_FILE\n\
      echo "DEVICE_IP=$DEVICE_IP" >> $CONFIG_FILE\n\
      echo "ADB_CONNECT_PORT=$ADB_CONNECT_PORT" >> $CONFIG_FILE\n\
      ;;\n\
      \n\
    3)\n\
      echo ""\n\
      echo "=== 跳过网络连接 ==="\n\
      echo "将使用 USB 连接的设备"\n\
      echo ""\n\
      \n\
      # 保存配置\n\
      echo "MODE=3" > $CONFIG_FILE\n\
      ;;\n\
      \n\
    *)\n\
      echo "❌ 无效的选项！"\n\
      return 1\n\
      ;;\n\
  esac\n\
  \n\
  return 0\n\
}\n\
\n\
# 主流程：检查配置文件\n\
if [ -f "$CONFIG_FILE" ]; then\n\
  echo ""\n\
  echo "🔍 检测到已保存的配置，尝试使用保存的配置连接..."\n\
  echo ""\n\
  \n\
  # 读取配置\n\
  source $CONFIG_FILE\n\
  \n\
  # 显示配置信息\n\
  case $MODE in\n\
    1)\n\
      echo "连接方式: Android 11+ 无线调试"\n\
      echo "设备 IP: $DEVICE_IP"\n\
      echo "配对端口: $ADB_PAIRING_PORT"\n\
      echo "连接端口: $ADB_CONNECT_PORT"\n\
      ;;\n\
    2)\n\
      echo "连接方式: 传统 TCP/IP 模式"\n\
      echo "设备 IP: $DEVICE_IP"\n\
      echo "连接端口: $ADB_CONNECT_PORT"\n\
      ;;\n\
    3)\n\
      echo "连接方式: USB 连接"\n\
      ;;\n\
  esac\n\
  echo ""\n\
  \n\
  # 尝试连接（跳过配对步骤）\n\
  connect_device $MODE "$DEVICE_IP" "$ADB_PAIRING_PORT" "$ADB_PAIRING_CODE" "$ADB_CONNECT_PORT" "true"\n\
  CONNECT_RESULT=$?\n\
  \n\
  if [ $CONNECT_RESULT -ne 0 ]; then\n\
    echo ""\n\
    echo "⚠️  使用保存的配置连接失败！"\n\
    echo ""\n\
    read -p "是否删除旧配置并重新配置？[Y/n]: " RECONFIG\n\
    RECONFIG=${RECONFIG:-Y}\n\
    \n\
    if [[ "$RECONFIG" =~ ^[Yy]$ ]]; then\n\
      echo ""\n\
      echo "删除旧配置..."\n\
      rm -f $CONFIG_FILE\n\
      echo ""\n\
      \n\
      # 重新配置\n\
      interactive_config\n\
      if [ $? -ne 0 ]; then\n\
        kill $APPIUM_PID\n\
        exit 1\n\
      fi\n\
      \n\
      # 重新读取配置\n\
      source $CONFIG_FILE\n\
      \n\
      # 再次尝试连接（需要配对）\n\
      connect_device $MODE "$DEVICE_IP" "$ADB_PAIRING_PORT" "$ADB_PAIRING_CODE" "$ADB_CONNECT_PORT" "false"\n\
      if [ $? -ne 0 ]; then\n\
        echo ""\n\
        echo "❌ 连接失败！请检查配置"\n\
        kill $APPIUM_PID\n\
        exit 1\n\
      fi\n\
    else\n\
      echo ""\n\
      echo "❌ 连接失败，退出程序"\n\
      kill $APPIUM_PID\n\
      exit 1\n\
    fi\n\
  fi\n\
  \n\
  sleep 2\n\
else\n\
  echo ""\n\
  echo "📝 首次使用，开始配置..."\n\
  \n\
  # 交互式配置\n\
  interactive_config\n\
  if [ $? -ne 0 ]; then\n\
    kill $APPIUM_PID\n\
    exit 1\n\
  fi\n\
  \n\
  # 读取配置\n\
  source $CONFIG_FILE\n\
  \n\
  # 执行连接（首次配置需要配对）\n\
  connect_device $MODE "$DEVICE_IP" "$ADB_PAIRING_PORT" "$ADB_PAIRING_CODE" "$ADB_CONNECT_PORT" "false"\n\
  if [ $? -ne 0 ]; then\n\
    echo ""\n\
    echo "❌ 连接失败！"\n\
    echo ""\n\
    case $MODE in\n\
      1)\n\
        echo "请检查:"\n\
        echo "1. 配对码和端口是否正确"\n\
        echo "2. 手机无线调试是否已开启"\n\
        echo "3. 手机和电脑是否在同一 WiFi 网络"\n\
        ;;\n\
      2)\n\
        echo "请检查:"\n\
        echo "1. 手机和电脑是否在同一 WiFi 网络"\n\
        echo "2. 是否已通过 USB 执行过: adb tcpip 5555"\n\
        ;;\n\
    esac\n\
    rm -f $CONFIG_FILE\n\
    kill $APPIUM_PID\n\
    exit 1\n\
  fi\n\
  \n\
  sleep 2\n\
fi\n\
\n\
# 显示已连接的设备\n\
echo ""\n\
echo "========================================"\n\
echo "已连接的设备列表:"\n\
adb devices\n\
echo "========================================"\n\
echo ""\n\
\n\
# 检查是否有设备连接\n\
DEVICE_COUNT=$(adb devices | grep -v "List" | grep "device" | wc -l)\n\
if [ "$DEVICE_COUNT" -eq 0 ]; then\n\
  echo "❌ 错误: 未检测到任何 Android 设备！"\n\
  echo ""\n\
  echo "请确保:"\n\
  echo "1. 手机已开启 USB 调试或无线调试"\n\
  echo "2. 网络连接配置正确"\n\
  echo "3. 或使用 USB 连接并挂载设备: docker run --privileged -v /dev/bus/usb:/dev/bus/usb ..."\n\
  echo ""\n\
  kill $APPIUM_PID\n\
  exit 1\n\
fi\n\
\n\
echo "✅ 设备连接成功！准备启动抢票脚本..."\n\
echo ""\n\
\n\
echo ""\n\
echo "========================================"\n\
echo "开始执行抢票任务（V2 版本）"\n\
echo "========================================"\n\
cd damai_appium && python3 damai_app_v3.py\n\
\n\
# 脚本执行完毕后保持 Appium 运行\n\
echo ""\n\
echo "抢票脚本执行完毕"\n\
\n\
echo ""\n\
echo "💡 提示: 如需重新配置连接，可手动删除配置文件:"\n\
echo "   docker exec <container_id> rm /app/adb_config.txt"\n\
echo ""\n\
echo "Appium Server 继续运行中..."\n\
wait $APPIUM_PID\n\
' > /app/start.sh && chmod +x /app/start.sh

# 默认启动命令
CMD ["/app/start.sh"]
