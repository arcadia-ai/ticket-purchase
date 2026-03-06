# Damai Ticket Purchase Automation

大麦 App 自动抢票系统，基于 uiautomator2 (ATX) 框架。

## 特性

- **uiautomator2 直连** — 无需 Appium Server / Java / Node.js，直接通过 HTTP 控制设备
- **精准定时** — NTP 校时 + 毫秒级忙轮询，精准卡点抢票
- **智能识别** — u2 原生选择器 + 可选 Ollama LLM 回退
- **自动恢复** — 后台弹窗关闭、步骤重试、页面回退
- **关键截图** — 每个步骤自动截图，方便调试
- **Docker 部署** — 轻量镜像 (~300MB)，一键启动

## 快速开始

### 1. 安装依赖

```bash
# 安装 uv (如果没有)
pip install uv

# 安装项目依赖
uv pip install -e .

# 如需 Ollama 支持
uv pip install -e ".[ollama]"
```

### 2. 配置

```bash
# 复制配置模板
cp config/config.example.yaml config/config.yaml
cp config/.env.example config/.env

# 编辑配置
# config/.env      — 设备 IP、端口、日志级别
# config/config.yaml — 演出关键词、城市、票价、购票人等
```

### 3. 手机准备

1. 开启「开发者选项」→「无线调试」
2. 确保手机和运行设备在同一局域网
3. 获取手机 IP 地址，填入 `config/.env` 的 `DEVICE_IP`
4. 安装大麦 App 并登录账号

### 4. 运行

```bash
# 本地直接运行
./start.sh

# 立即执行（忽略定时）
./start.sh --now

# Docker 运行
./start.sh --docker
```

或直接用 Python：

```bash
python -m ticket_purchase.main --config config/config.yaml --now
```

## 配置说明

### config/.env

| 变量 | 说明 | 默认值 |
|------|------|--------|
| DEVICE_IP | 手机 IP 地址 | 192.168.1.100 |
| DEVICE_PORT | ADB 端口 | 5555 |
| OLLAMA_ENABLED | 启用 Ollama 智能识别 | false |
| OLLAMA_HOST | Ollama 服务地址 | http://localhost:11434 |
| LOG_LEVEL | 日志级别 | INFO |

### config/config.yaml

| 字段 | 说明 | 示例 |
|------|------|------|
| keyword | 搜索关键词 | "周杰伦" |
| city | 城市 | "上海" |
| date | 日期（可选） | "10.04" |
| price_index | 票价索引 (0开始，低到高) | 0 |
| users | 购票人列表 | ["张三"] |
| target_time | 开抢时间（空=立即） | "2026-03-10 10:00:00" |
| if_commit_order | 是否自动提交订单 | true |
| max_retry | 最大重试次数 | 3 |

## 项目结构

```
src/ticket_purchase/
├── main.py          # 入口
├── connection.py    # ADB 连接 + u2 设备初始化
├── monitor.py       # 页面状态监控
├── detector.py      # 元素识别（u2 + Ollama）
├── executor.py      # UI 操作执行
├── scheduler.py     # NTP 定时调度
├── workflow.py      # 抢票流程编排
├── recovery.py      # 异常恢复
└── log.py           # 日志 + 截图
```

详细架构文档：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Docker 部署

```bash
# 一键启动
./start.sh --docker

# 或手动
docker compose up --build
```

镜像基于 `python:3.12-slim`，仅安装 adb + Python 依赖，约 300MB。

## 测试设备

- OnePlus 11 (Android 15)
- OPPO Find X8 Pro

## License

MIT
