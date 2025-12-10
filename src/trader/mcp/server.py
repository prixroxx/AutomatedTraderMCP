"""
MCP Server for Automated Trading System.

This module implements the Model Context Protocol server using FastMCP,
providing tools for trading operations accessible to LLMs like Claude.
"""

import os
import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..api.client import GrowwClient
from ..risk.manager import RiskManager
from ..risk.kill_switch import KillSwitch
from ..gtt.storage import GTTStorage
from ..gtt.executor import GTTExecutor
from ..gtt.monitor import GTTMonitor
from ..core.config import get_config
from ..core.logging_config import get_logger

logger = get_logger(__name__)


# Create FastMCP server
mcp = FastMCP(
    name="trader-mcp",
    version="0.1.0",
    dependencies=["growwapi", "pydantic", "structlog", "python-dotenv"]
)


class AppContext:
    """
    Application context holding all initialized components.

    This context is passed to all MCP tools via the ctx parameter.
    """

    def __init__(
        self,
        groww_client: GrowwClient,
        risk_manager: RiskManager,
        kill_switch: KillSwitch,
        gtt_storage: GTTStorage,
        gtt_executor: GTTExecutor,
        gtt_monitor: GTTMonitor,
        config: Any
    ):
        self.groww_client = groww_client
        self.risk_manager = risk_manager
        self.kill_switch = kill_switch
        self.gtt_storage = gtt_storage
        self.gtt_executor = gtt_executor
        self.gtt_monitor = gtt_monitor
        self.config = config


@asynccontextmanager
async def app_lifespan():
    """
    Application lifecycle manager.

    Initializes all components on startup and cleans up on shutdown.

    Yields:
        AppContext with all initialized components
    """
    logger.info("🚀 Starting Automated Trading MCP Server...")

    # Load configuration
    config = get_config()

    logger.info(
        "Configuration loaded",
        paper_mode=config.is_paper_mode(),
        max_portfolio=config.get('risk.max_portfolio_value'),
        max_position=config.get('risk.max_position_size')
    )

    # Initialize Groww API client
    logger.info("Initializing Groww API client...")
    groww_client = GrowwClient(config=config)
    await groww_client.initialize()

    logger.info(
        "Groww client initialized",
        paper_mode=groww_client.is_paper_mode()
    )

    # Initialize risk manager
    logger.info("Initializing risk manager...")
    risk_manager = RiskManager(groww_client, config=config)

    # Initialize kill switch
    logger.info("Initializing kill switch...")
    kill_switch = KillSwitch(risk_manager, config=config)

    # Start kill switch monitoring
    logger.info("Starting kill switch monitoring...")
    await kill_switch.start_monitoring()

    # Initialize GTT system
    logger.info("Initializing GTT system...")

    # GTT storage
    data_dir = Path(__file__).parent.parent.parent.parent / "data"
    gtt_storage = GTTStorage(db_path=data_dir / "gtt_orders.db")

    # GTT executor
    gtt_executor = GTTExecutor(groww_client, gtt_storage, risk_manager)

    # GTT monitor
    gtt_monitor = GTTMonitor(groww_client, gtt_storage, gtt_executor, check_interval=30)

    # Start GTT monitoring
    logger.info("Starting GTT monitoring...")
    await gtt_monitor.start()

    # Create application context
    context = AppContext(
        groww_client=groww_client,
        risk_manager=risk_manager,
        kill_switch=kill_switch,
        gtt_storage=gtt_storage,
        gtt_executor=gtt_executor,
        gtt_monitor=gtt_monitor,
        config=config
    )

    logger.info("✅ MCP Server started successfully")
    logger.info(
        "Server status",
        paper_mode=groww_client.is_paper_mode(),
        kill_switch_active=kill_switch.is_active(),
        gtt_monitoring=gtt_monitor.is_running()
    )

    # Yield context to server
    yield context

    # Cleanup on shutdown
    logger.info("🛑 Shutting down MCP Server...")

    # Stop GTT monitoring
    logger.info("Stopping GTT monitoring...")
    await gtt_monitor.stop()

    # Stop kill switch monitoring
    logger.info("Stopping kill switch monitoring...")
    await kill_switch.stop_monitoring()

    # Close GTT storage
    logger.info("Closing GTT storage...")
    await gtt_storage.close()

    logger.info("✅ MCP Server shutdown complete")


# Set lifespan for FastMCP
mcp.lifespan(app_lifespan)


# Import tool modules (this registers the tools with the MCP server)
from . import tools  # noqa: E402, F401


def main():
    """
    Main entry point for MCP server.

    Run with: python -m src.trader.mcp.server
    """
    logger.info("Starting MCP Server via main()")

    # Check for API credentials
    if not os.getenv('GROWW_API_KEY') or not os.getenv('GROWW_SECRET'):
        logger.error(
            "Missing Groww API credentials. "
            "Set GROWW_API_KEY and GROWW_SECRET in environment."
        )
        return

    # Check paper mode
    paper_mode = os.getenv('FORCE_PAPER_MODE', '1')
    if paper_mode == '1':
        logger.warning("⚠️  PAPER MODE ENABLED - Orders will be simulated")
    else:
        logger.warning("🚨 LIVE MODE - Orders will be placed on real account!")
        logger.warning("⚠️  Ensure you have tested thoroughly in paper mode first")

    # Run server
    try:
        mcp.run()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise


if __name__ == "__main__":
    main()
