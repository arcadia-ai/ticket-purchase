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

# 创建启动脚本（适配V2版本）
RUN echo '#!/bin/bash\n\
echo "========================================"\n\
echo "大麦抢票系统 V2 - Docker版"\n\
echo "========================================"\n\
echo ""\n\
echo "启动Appium Server（带relaxed-security支持）..."\n\
appium --address 0.0.0.0 --port 4723 --relaxed-security &\n\
APPIUM_PID=$!\n\
\n\
echo "等待Appium Server启动..."\n\
sleep 5\n\
\n\
# 如果设置了DEVICE_IP环境变量，通过网络连接ADB\n\
if [ -n "$DEVICE_IP" ]; then\n\
  echo "通过网络ADB连接设备: $DEVICE_IP:5555"\n\
  adb connect $DEVICE_IP:5555\n\
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
  echo "❌ 错误: 未检测到任何Android设备！"\n\
  echo ""\n\
  echo "请确保:"\n\
  echo "1. 手机已开启USB调试"\n\
  echo "2. 已通过网络ADB连接（设置DEVICE_IP环境变量）"\n\
  echo "3. 或使用 --privileged 和 -v /dev/bus/usb:/dev/bus/usb 挂载USB设备"\n\
  echo ""\n\
  kill $APPIUM_PID\n\
  exit 1\n\
fi\n\
\n\
echo "✅ 设备连接成功！准备启动抢票脚本..."\n\
echo ""\n\
echo "========================================"\n\
echo "开始执行抢票任务（V2版本）"\n\
echo "========================================"\n\
cd damai_appium && python3 damai_app_v2.py\n\
\n\
# 脚本执行完毕后保持Appium运行\n\
echo ""\n\
echo "抢票脚本执行完毕"\n\
echo "Appium Server 继续运行中..."\n\
wait $APPIUM_PID\n\
' > /app/start.sh && chmod +x /app/start.sh

# 默认启动命令
CMD ["/app/start.sh"]
