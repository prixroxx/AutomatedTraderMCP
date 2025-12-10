"""
Integration Tests for Trading System.

Tests the integration of multiple components working together.
"""

import pytest
import asyncio
from datetime import datetime

from src.trader.core.config import get_config
from src.trader.api.client import GrowwClient
from src.trader.risk.manager import RiskManager
from src.trader.risk.kill_switch import KillSwitch
from src.trader.gtt.storage import GTTStorage
from src.trader.gtt.executor import GTTExecutor


@pytest.fixture
def config():
    """Get configuration."""
    return get_config()


@pytest.mark.asyncio
async def test_config_loading(config):
    """Test configuration loads correctly."""
    assert config is not None
    assert config.is_paper_mode() is True  # Should default to paper mode
    assert config.get('risk.max_portfolio_value') > 0
    assert 'MAX_SINGLE_ORDER_VALUE' in config.hard_limits


@pytest.mark.asyncio
async def test_client_initialization(config):
    """Test Groww client initializes in paper mode."""
    client = GrowwClient(config=config)

    assert client.is_paper_mode() is True
    assert client.config == config


@pytest.mark.asyncio
async def test_risk_manager_initialization(config):
    """Test risk manager initializes with client."""
    client = GrowwClient(config=config)
    risk_manager = RiskManager(client, config=config)

    assert risk_manager is not None
    assert risk_manager.config == config
    assert risk_manager.groww_client == client


@pytest.mark.asyncio
async def test_kill_switch_initialization(config):
    """Test kill switch initializes with risk manager."""
    client = GrowwClient(config=config)
    risk_manager = RiskManager(client, config=config)
    kill_switch = KillSwitch(risk_manager, config=config)

    assert kill_switch is not None
    assert kill_switch.is_active() is False  # Should start inactive


@pytest.mark.asyncio
async def test_kill_switch_activation(config):
    """Test kill switch can be activated and deactivated."""
    client = GrowwClient(config=config)
    risk_manager = RiskManager(client, config=config)
    kill_switch = KillSwitch(risk_manager, config=config)

    # Activate
    kill_switch.activate(reason="test", message="Integration test")
    assert kill_switch.is_active() is True

    # Note: Deactivation requires admin approval and cooldown in real scenario
    # For testing, we just verify the activation worked


@pytest.mark.asyncio
async def test_gtt_storage_operations(tmp_path):
    """Test GTT storage CRUD operations."""
    db_path = tmp_path / "test_gtt.db"
    storage = GTTStorage(db_path=db_path)

    # Create GTT
    gtt_id = await storage.create_gtt(
        symbol="TESTSTOCK",
        exchange="NSE",
        trigger_price=100.0,
        order_type="LIMIT",
        action="BUY",
        quantity=1,
        limit_price=100.0
    )

    assert gtt_id is not None
    assert gtt_id > 0

    # Get GTT
    gtt = await storage.get_gtt(gtt_id)
    assert gtt is not None
    assert gtt.symbol == "TESTSTOCK"
    assert gtt.trigger_price == 100.0

    # Get active GTTs
    active_gtts = await storage.get_active_gtts()
    assert len(active_gtts) > 0

    # Cancel GTT
    cancelled = await storage.cancel_gtt(gtt_id)
    assert cancelled is not None
    assert cancelled.status == "CANCELLED"

    # Clean up
    await storage.close()


@pytest.mark.asyncio
async def test_gtt_executor_validation(config, tmp_path):
    """Test GTT executor validates with risk manager."""
    db_path = tmp_path / "test_gtt.db"
    storage = GTTStorage(db_path=db_path)

    client = GrowwClient(config=config)
    risk_manager = RiskManager(client, config=config)
    executor = GTTExecutor(client, storage, risk_manager)

    assert executor is not None
    assert executor.groww_client == client
    assert executor.risk_manager == risk_manager

    await storage.close()


@pytest.mark.asyncio
async def test_paper_mode_enforcement(config):
    """Test that paper mode is enforced throughout the system."""
    client = GrowwClient(config=config)
    risk_manager = RiskManager(client, config=config)

    # Verify paper mode at all levels
    assert config.is_paper_mode() is True
    assert client.is_paper_mode() is True

    # Get risk status
    status = await risk_manager.get_status()
    assert status is not None


@pytest.mark.asyncio
async def test_order_validation_pipeline(config):
    """Test order goes through full validation pipeline."""
    client = GrowwClient(config=config)
    risk_manager = RiskManager(client, config=config)

    # Validate a reasonable order
    validation = await risk_manager.validate_order(
        symbol="TESTSTOCK",
        quantity=1,
        price=100.0,
        transaction_type="BUY"
    )

    assert validation is not None
    assert hasattr(validation, 'approved')
    assert hasattr(validation, 'reason')


@pytest.mark.asyncio
async def test_hard_limits_enforcement(config):
    """Test hard limits cannot be exceeded."""
    client = GrowwClient(config=config)
    risk_manager = RiskManager(client, config=config)

    # Try to place order exceeding hard limit
    max_single_order = config.hard_limits['MAX_SINGLE_ORDER_VALUE']

    validation = await risk_manager.validate_order(
        symbol="TESTSTOCK",
        quantity=1000,  # Large quantity
        price=max_single_order + 1000,  # Exceeds hard limit
        transaction_type="BUY"
    )

    # Should be rejected
    assert validation.approved is False
    assert "hard limit" in validation.reason.lower() or "exceeds" in validation.reason.lower()


def test_component_integration():
    """Test that all major components can be imported."""
    # Try importing all major components
    from src.trader.core.config import get_config
    from src.trader.core.logging_config import get_logger
    from src.trader.api.client import GrowwClient
    from src.trader.api.models import Order, Quote, Position
    from src.trader.risk.manager import RiskManager
    from src.trader.risk.kill_switch import KillSwitch
    from src.trader.gtt.storage import GTTStorage
    from src.trader.gtt.executor import GTTExecutor
    from src.trader.gtt.monitor import GTTMonitor
    from src.trader.backtesting.engine import BacktestEngine
    from src.trader.strategies.momentum import MomentumStrategy
    from src.trader.strategies.mean_reversion import MeanReversionStrategy
    from src.trader.data.news_fetcher import NewsFetcher
    from src.trader.mcp.server import mcp

    # If we got here, all imports succeeded
    assert True


def test_mcp_tools_registered():
    """Test that MCP tools are registered."""
    from src.trader.mcp.server import mcp

    # Check that the MCP server exists
    assert mcp is not None
    assert mcp.name == "trader-mcp"
    assert mcp.version == "0.1.0"
