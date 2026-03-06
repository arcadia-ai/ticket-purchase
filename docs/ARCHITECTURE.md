# Ticket-Purchase 技术架构文档

## 项目概述

大麦 App 自动抢票系统，基于 uiautomator2 (ATX) 框架，通过 ADB 无线连接 Android 设备，自动化完成搜索、选票、下单全流程。

## 技术栈

| 组件 | 技术选型 | 说明 |
|------|----------|------|
| 自动化框架 | uiautomator2 (ATX) | 直连设备，无需 Appium Server |
| 智能识别(可选) | Ollama / DeepSeek LLM | 动态分析 XML 定位元素，默认关闭，支持多后端 |
| 包管理 | uv | 快速 Python 包管理器 |
| 日志 | loguru | 控制台 + 文件 + 截图 |
| 配置 | .env + YAML | 设备配置与业务配置分离 |
| 容器化 | Docker + docker-compose | 轻量级镜像，一键部署 |
| Python | 3.12+ | 最新稳定版 |

## 架构图

```
Python 主控程序 (main.py)
    ├── ADB 无线连接模块 (connection.py)
    │     └── adb connect → u2.connect() → device 对象
    ├── 屏幕监控模块 (monitor.py)
    │     └── 页面状态判断 / 元素等待
    ├── 智能识别模块 (detector.py)
    │     ├── u2 原生选择器 (resourceId > text > xpath)
    │     └── LLM 回退 (可选: Ollama / DeepSeek)
    ├── 操作执行模块 (executor.py)
    │     └── tap / click / swipe / input
    ├── 定时调度模块 (scheduler.py)
    │     └── NTP 校时 + 精准倒计时
    ├── 抢票流程编排 (workflow.py)
    │     └── 搜索 → 选城市 → 购买 → 选价 → 选人 → 提交
    ├── 异常恢复模块 (recovery.py)
    │     └── 弹窗关闭 / 步骤重试 / 页面回退
    └── 日志截图模块 (log.py)
          └── loguru + 关键步骤截图
```

## 目录结构

```
ticket-purchase/
├── src/
│   └── ticket_purchase/
│       ├── __init__.py
│       ├── main.py              # 入口
│       ├── connection.py        # ADB 连接
│       ├── monitor.py           # 页面监控
│       ├── detector.py          # 元素识别
│       ├── executor.py          # 操作执行
│       ├── scheduler.py         # 定时调度
│       ├── workflow.py          # 流程编排
│       ├── recovery.py          # 异常恢复
│       └── log.py               # 日志管理
├── config/
│   ├── config.yaml              # 业务配置
│   ├── config.example.yaml      # 配置模板
│   └── .env.example             # 环境变量模板
├── logs/                        # 运行日志
├── screenshots/                 # 截图
├── docs/
│   ├── ARCHITECTURE.md          # 本文档
│   └── plans/                   # 设计文档
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── start.sh
├── .gitignore
├── CLAUDE.md
└── README.md
```

## 模块详细设计

### connection.py — ADB 连接
- 输入：设备 IP + 端口（从 .env）
- 输出：u2.Device 对象
- 流程：`adb connect` → 验证 → `u2.connect()` → 返回
- 重试：连接失败自动重试 3 次，间隔 2 秒

### monitor.py — 页面监控
- `wait_for_element(selector, timeout)` — 等待元素出现
- `current_app()` — 获取前台应用包名
- `is_target_app()` — 检查是否在大麦 App

### detector.py — 元素识别
- 统一接口：`find(desc, **kwargs)` / `find_all(desc, **kwargs)`
- 优先级：resourceId → text/description → className → LLM 回退
- LLM 通过 `LLM_PROVIDER` 环境变量控制，支持两种后端：
  - `ollama` — 本地/内网部署的 Ollama 服务
  - `deepseek` — DeepSeek API（兼容 OpenAI SDK）
- 内部通过 `LLMClient` 统一抽象层封装，对上层透明

### executor.py — 操作执行
- `tap(x, y)` — 坐标点击
- `click(element)` — 元素点击
- `swipe(direction, scale)` — 方向滑动
- `input_text(element, text)` — 文本输入
- `press_key(key)` — 按键（如 Enter）

### scheduler.py — 定时调度
- NTP 校时获取精确时间
- 粗等待（>1s 时 sleep）+ 精等待（<1s 时 busy-wait）
- `target_time` 为空则立即执行

### workflow.py — 流程编排
- 9 步抢票流程，每步有日志和截图
- 步骤间可配置等待时间
- 失败交给 recovery 处理

### recovery.py — 异常恢复
- 后台守护线程定期检查并关闭弹窗
- 单步重试（最多 3 次）
- 整体重试（可配置 max_retry）
- 错误页面自动回退

### log.py — 日志管理
- loguru 配置：控制台彩色 + 文件轮转
- 关键步骤自动截图到 screenshots/
- 日志级别通过 .env 配置

## 配置说明

### .env（设备/环境）
```
DEVICE_IP=192.168.1.100
DEVICE_PORT=5555

# LLM 智能识别（可选，留空禁用）
LLM_PROVIDER=              # "ollama" 或 "deepseek"

# Ollama 配置（LLM_PROVIDER=ollama 时生效）
OLLAMA_HOST=http://192.168.123.200:11434
OLLAMA_MODEL=gpt-oss:120b-cloud

# DeepSeek 配置（LLM_PROVIDER=deepseek 时生效）
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

LOG_LEVEL=INFO
```

### config.yaml（业务）
```yaml
keyword: "演出名称"
city: "城市"
date: "日期"
price_index: 0
users:
  - "购票人姓名"
target_time: ""
if_commit_order: true
max_retry: 3
```

## Docker 部署
- 基础镜像：python:3.12-slim
- 只安装：adb + uv + Python 依赖
- 镜像大小：~300MB
- 网络模式：host（直连局域网设备）

## 国内网络适配
- **apt**: 阿里云镜像 (mirrors.aliyun.com)
- **PyPI**: 清华镜像 (pypi.tuna.tsinghua.edu.cn)，在 pyproject.toml `[tool.uv]` 和 Dockerfile 中均已配置
- **uv 安装**: ghfast.top 代理 GitHub 下载，失败回退官方源
- **NTP**: 优先使用 ntp.aliyun.com / ntp.tencent.com

---

## 变更日志

### v2.1.0 (2026-03-06) — LLM 多后端 & 国内适配
- **新增**: DeepSeek API 支持（兼容 OpenAI SDK），通过 `LLM_PROVIDER=deepseek` 启用
- **重构**: detector.py 新增 `LLMClient` 统一抽象层，替代原 Ollama 硬编码
- **重构**: `OLLAMA_ENABLED` 环境变量改为 `LLM_PROVIDER`（"ollama" / "deepseek" / 留空）
- **新增**: pyproject.toml 可选依赖组 `deepseek`（openai SDK）和 `llm`（全部 LLM 依赖）
- **优化**: Dockerfile apt 使用阿里云镜像
- **优化**: Dockerfile uv 安装使用 ghfast.top 代理（国内 GitHub 加速）
- **优化**: Dockerfile / pyproject.toml PyPI 使用清华镜像源

### v2.0.0 (2026-03-06) — 架构重构
- **Breaking**: 从 Appium + Selenium 迁移到 uiautomator2 (ATX)
- **Breaking**: 配置格式从 JSONC 改为 .env + YAML
- **Breaking**: 包管理从 Poetry 改为 uv
- **移除**: Java、Node.js、Appium Server 依赖
- **移除**: damai_appium/ 目录（旧代码）
- **新增**: 模块化架构（connection/monitor/detector/executor/scheduler/workflow/recovery/log）
- **新增**: NTP 精准定时调度
- **新增**: 后台弹窗自动关闭
- **新增**: 关键步骤自动截图
- **新增**: Docker 轻量化部署（镜像 >2GB → ~300MB）
- **新增**: start.sh 一键启动脚本
- **优化**: 设备连接从 Appium Server 中转改为直连（延迟降低 75%）
