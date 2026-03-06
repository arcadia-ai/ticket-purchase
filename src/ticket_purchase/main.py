"""自动购票系统入口。"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from .connection import init_device
from .log import setup_logging
from .scheduler import wait_until
from .workflow import AutonomousWorkflow, TicketConfig, TicketWorkflow

# 默认路径
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG = BASE_DIR / "config" / "config.yaml"
DEFAULT_ENV = BASE_DIR / "config" / ".env"


def main():
    parser = argparse.ArgumentParser(description="大麦自动购票系统")
    parser.add_argument("--config", "-c", default=str(DEFAULT_CONFIG),
                        help="config.yaml 配置文件路径")
    parser.add_argument("--env", default=str(DEFAULT_ENV),
                        help=".env 环境文件路径")
    parser.add_argument("--now", action="store_true",
                        help="忽略定时设置，立即执行")
    parser.add_argument("--auto", action="store_true",
                        help="自主模式：LLM 完全自主控制流程")
    args = parser.parse_args()

    # 加载环境变量
    env_path = Path(args.env)
    if env_path.exists():
        load_dotenv(env_path)

    # 设置日志
    log_level = os.getenv("LOG_LEVEL", "INFO")
    setup_logging(log_level)

    # 加载配置
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error("配置文件未找到: {}", config_path)
        logger.info("请复制 config/config.example.yaml 到 config/config.yaml 并编辑")
        sys.exit(1)

    config = TicketConfig.load(str(config_path))
    logger.info("配置已加载: keyword='{}', city='{}', users={}",
                config.keyword, config.city, config.users)

    # 连接设备
    device_ip = os.getenv("DEVICE_IP", "127.0.0.1")
    device_port = int(os.getenv("DEVICE_PORT", "5555"))

    try:
        device = init_device(device_ip, device_port)
    except ConnectionError as e:
        logger.error("设备连接失败: {}", e)
        sys.exit(1)

    # 等待目标时间（除非使用 --now）
    if not args.now:
        wait_until(config.target_time)

    # 执行工作流
    if args.auto:
        # 自主模式：LLM 完全控制
        logger.info("启动自主模式（LLM 控制）")
        workflow = AutonomousWorkflow(device, config)
        success = workflow.run()
    else:
        # 传统模式：代码控制流程
        workflow = TicketWorkflow(device, config)
        success = workflow.run_with_retry()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
