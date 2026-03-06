#!/bin/bash
set -e

echo "========================================"
echo "  Damai Ticket Purchase Automation v2.0"
echo "========================================"

# Detect if running in Docker
IN_DOCKER=false
if [ -f /.dockerenv ] || grep -q docker /proc/1/cgroup 2>/dev/null; then
    IN_DOCKER=true
fi

# Parse arguments
RUN_NOW=""
USE_DOCKER=false
CONFIG_PATH="config/config.yaml"
ENV_PATH="config/.env"

while [[ $# -gt 0 ]]; do
    case $1 in
        --docker) USE_DOCKER=true; shift ;;
        --now) RUN_NOW="--now"; shift ;;
        --config) CONFIG_PATH="$2"; shift 2 ;;
        *) shift ;;
    esac
done

# Docker mode: build and run container
if [ "$USE_DOCKER" = true ] && [ "$IN_DOCKER" = false ]; then
    echo "Starting in Docker mode..."

    # Check config exists
    if [ ! -f "$CONFIG_PATH" ]; then
        echo "ERROR: Config not found at $CONFIG_PATH"
        echo "Copy config/config.example.yaml to config/config.yaml and edit it"
        exit 1
    fi
    if [ ! -f "$ENV_PATH" ]; then
        echo "ERROR: .env not found at $ENV_PATH"
        echo "Copy config/.env.example to config/.env and edit it"
        exit 1
    fi

    docker compose up --build
    exit $?
fi

# Direct mode (local or inside Docker)

# Check adb
if ! command -v adb &>/dev/null; then
    echo "ERROR: adb not found. Install Android platform-tools."
    exit 1
fi

# Connect device via ADB
DEVICE_IP="${DEVICE_IP:-127.0.0.1}"
DEVICE_PORT="${DEVICE_PORT:-5555}"
echo "Connecting to device: ${DEVICE_IP}:${DEVICE_PORT}"
adb connect "${DEVICE_IP}:${DEVICE_PORT}" || true
sleep 1

# Verify device
DEVICE_COUNT=$(adb devices | grep -c "device$" || true)
if [ "$DEVICE_COUNT" -eq 0 ]; then
    echo "ERROR: No Android device connected!"
    echo "Check: 1) Device IP/port  2) Wireless debugging enabled  3) Same network"
    exit 1
fi
echo "Device connected."
adb devices

# Run the automation
echo ""
echo "Starting ticket automation..."
# Set PYTHONPATH for local (non-installed) development
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$(dirname "$0")/src"
python -m ticket_purchase.main --config "$CONFIG_PATH" --env "$ENV_PATH" $RUN_NOW
