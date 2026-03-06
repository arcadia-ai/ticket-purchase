"""Entry point for the ticket purchase automation."""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from .connection import init_device
from .log import setup_logging
from .scheduler import wait_until
from .workflow import TicketConfig, TicketWorkflow

# Default paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG = BASE_DIR / "config" / "config.yaml"
DEFAULT_ENV = BASE_DIR / "config" / ".env"


def main():
    parser = argparse.ArgumentParser(description="Damai ticket purchase automation")
    parser.add_argument("--config", "-c", default=str(DEFAULT_CONFIG),
                        help="Path to config.yaml")
    parser.add_argument("--env", default=str(DEFAULT_ENV),
                        help="Path to .env file")
    parser.add_argument("--now", action="store_true",
                        help="Ignore target_time, run immediately")
    args = parser.parse_args()

    # Load environment
    env_path = Path(args.env)
    if env_path.exists():
        load_dotenv(env_path)

    # Setup logging
    log_level = os.getenv("LOG_LEVEL", "INFO")
    setup_logging(log_level)

    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error("Config file not found: {}", config_path)
        logger.info("Copy config/config.example.yaml to config/config.yaml and edit it")
        sys.exit(1)

    config = TicketConfig.load(str(config_path))
    logger.info("Config loaded: keyword='{}', city='{}', users={}",
                config.keyword, config.city, config.users)

    # Connect to device
    device_ip = os.getenv("DEVICE_IP", "127.0.0.1")
    device_port = int(os.getenv("DEVICE_PORT", "5555"))

    try:
        device = init_device(device_ip, device_port)
    except ConnectionError as e:
        logger.error("Device connection failed: {}", e)
        sys.exit(1)

    # Wait for target time (unless --now)
    if not args.now:
        wait_until(config.target_time)

    # Run workflow
    workflow = TicketWorkflow(device, config)
    success = workflow.run_with_retry()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
