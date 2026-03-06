# Ticket-Purchase Refactor: Appium -> uiautomator2 (ATX)

Date: 2026-03-06

## Decisions

- Framework: uiautomator2 (ATX) replacing Appium + Selenium
- Ollama: kept as optional fallback (config switch, default off)
- Connection: ADB wireless only
- Scheduling: built-in countdown timer (target_time set = wait, empty = immediate)
- OCR: deferred, add later if needed
- Config: .env (device/env) + YAML (business logic)
- Package manager: uv
- Logging: loguru, console + file + key-step screenshots

## Project Structure

```
ticket-purchase/
├── src/
│   └── ticket_purchase/
│       ├── __init__.py
│       ├── main.py              # Entry point
│       ├── connection.py        # ADB wireless + u2 device init
│       ├── monitor.py           # Page state detection, element waiting
│       ├── detector.py          # Element finding: u2 selectors + Ollama fallback
│       ├── executor.py          # UI actions: tap, click, swipe, input
│       ├── scheduler.py         # NTP sync + countdown timer
│       ├── workflow.py          # Ticket grabbing flow orchestration
│       ├── recovery.py          # Error recovery, popup dismiss, retry
│       └── log.py               # Loguru setup + screenshot management
├── config/
│   ├── config.example.yaml
│   └── .env.example
├── logs/
├── screenshots/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── start.sh
├── CLAUDE.md
└── README.md
```

## Module Responsibilities

### connection.py
- `adb connect <ip:port>` -> verify -> `u2.connect(ip)` -> return device
- Auto-retry 3 times on failure, connection health check

### monitor.py
- `wait_for_element(selector, timeout)` - wait for element
- `current_activity()` - get current Activity
- `is_page(page_name)` - check current page

### detector.py
- Unified `find(desc, **selectors)` interface
- Priority: resourceId > text/description > XPath > Ollama (optional)
- `find_all(desc, **selectors)` for multiple elements

### executor.py
- `tap(x, y)` - coordinate tap (fastest)
- `click(element)` - element click
- `swipe(direction)` - swipe
- `input_text(element, text)` - text input
- Optional screenshot after each action

### scheduler.py
- Optional NTP time sync
- Coarse wait (sleep when >1s away)
- Fine wait (busy-wait last 1s, ms precision)
- Empty target_time = run immediately

### workflow.py
- Step-by-step ticket grabbing orchestration:
  1. Open Damai App
  2. Search keyword -> select event
  3. Select city, date
  4. Wait for sale time (scheduler)
  5. Click "buy now"
  6. Select price tier
  7. Select users
  8. Adjust quantity
  9. Submit order (controlled by if_commit_order)
- Each step: log + optional screenshot, failure -> recovery

### recovery.py
- Background popup dismissal (daemon thread)
- Step-level retry (max 3)
- Flow-level retry (configurable max_retry)
- Page navigation recovery
- Timeout fallback with screenshot

### log.py
- Loguru: console (colored) + file (rotating)
- Screenshot capture at key steps
- Log level from .env

## Config Design

### .env
```
DEVICE_IP=192.168.1.100
DEVICE_PORT=5555
OLLAMA_ENABLED=false
OLLAMA_HOST=http://192.168.123.200:11434
OLLAMA_MODEL=gpt-oss:120b-cloud
LOG_LEVEL=INFO
```

### config.yaml
```yaml
keyword: ""
city: ""
date: ""
price_index: 1
users:
  - ""
target_time: ""
if_commit_order: true
max_retry: 3
```

## Docker Design

- Base: python:3.12-slim (~150MB)
- Install: android-tools (adb) + uv + Python deps
- No Java, Node.js, or Appium needed
- Estimated image: ~300MB (down from >2GB)
- network_mode: host for LAN device access
- Volumes: config/, logs/, screenshots/

## Performance Comparison

| Aspect | Old (Appium) | New (u2/ATX) |
|---|---|---|
| Docker image | >2GB | ~300MB |
| Dependencies | Java+Node+Appium+Selenium | Python+adb |
| Connection | Appium Server relay | Direct HTTP to device |
| Click speed | ~200ms | ~50ms |
