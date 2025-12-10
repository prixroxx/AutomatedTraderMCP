"""
Tests for GTT Executor.

Tests cover:
- GTT execution
- Risk validation integration
- Kill switch integration
- Error handling
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from src.trader.gtt.executor import GTTExecutor
from src.trader.api.models import GTTOrder, GTTStatus, Order
from src.trader.api.exceptions import GTTExecutionError, KillSwitchActive, OrderError


@pytest.fixture
def mock_groww_client():
    """Mock Groww client."""
    client = Mock()
    client.place_order = AsyncMock(return_value=Order(
        order_id="TEST123",
        symbol="RELIANCE",
        exchange="NSE",
        quantity=1,
        transaction_type="BUY",
        order_type="LIMIT",
        price=2490.0
    ))
    client.get_ltp = AsyncMock(return_value=2495.0)
    return client


@pytest.fixture
def mock_storage():
    """Mock GTT storage."""
    storage = Mock()
    storage.update_gtt_status = AsyncMock()
    storage.get_gtt = AsyncMock()
    return storage


@pytest.fixture
def mock_risk_manager():
    """Mock risk manager."""
    manager = Mock()
    manager.validate_order = AsyncMock()
    manager.record_order = AsyncMock()

    # Mock kill switch
    kill_switch = Mock()
    kill_switch.check_before_order = Mock()  # Doesn't raise by default
    manager.kill_switch = kill_switch

    return manager


@pytest.fixture
def executor(mock_groww_client, mock_storage, mock_risk_manager):
    """Create test executor."""
    return GTTExecutor(mock_groww_client, mock_storage, mock_risk_manager)


@pytest.fixture
def sample_gtt():
    """Create sample GTT order."""
    return GTTOrder(
        id=1,
        symbol="RELIANCE",
        exchange="NSE",
        trigger_price=2500.0,
        order_type="LIMIT",
        action="BUY",
        quantity=1,
        limit_price=2490.0,
        status=GTTStatus.ACTIVE.value,
        created_at=datetime.now()
    )


class TestGTTExecution:
    """Test GTT execution."""

    @pytest.mark.asyncio
    async def test_execute_successful(self, executor, sample_gtt, mock_risk_manager, mock_storage):
        """Test successful GTT execution."""
        # Setup validation to pass
        from src.trader.risk.manager import OrderValidation
        mock_risk_manager.validate_order.return_value = OrderValidation(approved=True)

        order = await executor.execute_gtt(sample_gtt, 2495.0)

        assert order is not None
        assert order.order_id == "TEST123"
        assert executor.stats['executions_succeeded'] == 1

        # Verify storage updated
        mock_storage.update_gtt_status.assert_called()

    @pytest.mark.asyncio
    async def test_execute_with_market_order(self, executor, mock_risk_manager, mock_storage, mock_groww_client):
        """Test executing MARKET order GTT."""
        from src.trader.risk.manager import OrderValidation
        mock_risk_manager.validate_order.return_value = OrderValidation(approved=True)

        market_gtt = GTTOrder(
            id=1,
            symbol="RELIANCE",
            exchange="NSE",
            trigger_price=2500.0,
            order_type="MARKET",
            action="BUY",
            quantity=1,
            status=GTTStatus.ACTIVE.value,
            created_at=datetime.now()
        )

        await executor.execute_gtt(market_gtt, 2495.0)

        # Verify place_order called without price
        call_kwargs = mock_groww_client.place_order.call_args[1]
        assert call_kwargs['price'] is None
        assert call_kwargs['order_type'] == "MARKET"


class TestKillSwitchIntegration:
    """Test kill switch integration."""

    @pytest.mark.asyncio
    async def test_kill_switch_blocks_execution(self, executor, sample_gtt, mock_risk_manager, mock_storage):
        """Test kill switch blocks execution."""
        # Setup kill switch to raise
        mock_risk_manager.kill_switch.check_before_order.side_effect = KillSwitchActive(
            "Kill switch active"
        )

        with pytest.raises(GTTExecutionError) as exc_info:
            await executor.execute_gtt(sample_gtt, 2495.0)

        assert "kill switch" in str(exc_info.value).lower()
        assert executor.stats['kill_switch_blocks'] == 1

        # Verify GTT marked as FAILED
        mock_storage.update_gtt_status.assert_called_with(
            sample_gtt.id,
            GTTStatus.FAILED.value,
            error_message=pytest.approx("Kill switch active", rel=1e-1),
            trigger_ltp=2495.0
        )


class TestRiskValidation:
    """Test risk validation integration."""

    @pytest.mark.asyncio
    async def test_risk_validation_rejection(self, executor, sample_gtt, mock_risk_manager, mock_storage):
        """Test risk validation rejection."""
        from src.trader.risk.manager import OrderValidation

        # Setup validation to reject
        mock_risk_manager.validate_order.return_value = OrderValidation(
            approved=False,
            reason="Daily loss limit exceeded"
        )

        with pytest.raises(GTTExecutionError) as exc_info:
            await executor.execute_gtt(sample_gtt, 2495.0)

        assert "risk validation failed" in str(exc_info.value).lower()
        assert executor.stats['risk_rejections'] == 1

        # Verify GTT marked as FAILED
        mock_storage.update_gtt_status.assert_called_with(
            sample_gtt.id,
            GTTStatus.FAILED.value,
            error_message=pytest.approx("Risk validation failed: Daily loss limit exceeded", rel=1e-1),
            trigger_ltp=2495.0
        )


class TestErrorHandling:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_order_placement_failure(self, executor, sample_gtt, mock_risk_manager, mock_storage, mock_groww_client):
        """Test handling order placement failure."""
        from src.trader.risk.manager import OrderValidation
        mock_risk_manager.validate_order.return_value = OrderValidation(approved=True)

        # Setup order placement to fail
        mock_groww_client.place_order.side_effect = OrderError("Order placement failed")

        with pytest.raises(GTTExecutionError):
            await executor.execute_gtt(sample_gtt, 2495.0)

        assert executor.stats['executions_failed'] == 1

    @pytest.mark.asyncio
    async def test_unexpected_error(self, executor, sample_gtt, mock_risk_manager, mock_storage):
        """Test handling unexpected error."""
        from src.trader.risk.manager import OrderValidation
        mock_risk_manager.validate_order.return_value = OrderValidation(approved=True)

        # Setup unexpected error
        mock_risk_manager.record_order.side_effect = Exception("Unexpected error")

        with pytest.raises(GTTExecutionError):
            await executor.execute_gtt(sample_gtt, 2495.0)


class TestRetry:
    """Test retry functionality."""

    @pytest.mark.asyncio
    async def test_retry_failed_gtt(self, executor, mock_storage, mock_groww_client, mock_risk_manager):
        """Test retrying failed GTT."""
        from src.trader.risk.manager import OrderValidation

        failed_gtt = GTTOrder(
            id=1,
            symbol="RELIANCE",
            exchange="NSE",
            trigger_price=2500.0,
            order_type="LIMIT",
            action="BUY",
            quantity=1,
            limit_price=2490.0,
            status=GTTStatus.FAILED.value,
            created_at=datetime.now()
        )

        mock_storage.get_gtt.return_value = failed_gtt
        mock_storage.update_gtt_status.return_value = failed_gtt
        mock_risk_manager.validate_order.return_value = OrderValidation(approved=True)

        # Trigger condition met
        mock_groww_client.get_ltp.return_value = 2495.0

        order = await executor.retry_failed_gtt(1)

        assert order is not None
        assert order.order_id == "TEST123"

    @pytest.mark.asyncio
    async def test_retry_non_failed_gtt_fails(self, executor, mock_storage):
        """Test retrying non-FAILED GTT fails."""
        active_gtt = GTTOrder(
            id=1,
            symbol="RELIANCE",
            exchange="NSE",
            trigger_price=2500.0,
            order_type="LIMIT",
            action="BUY",
            quantity=1,
            limit_price=2490.0,
            status=GTTStatus.ACTIVE.value,
            created_at=datetime.now()
        )

        mock_storage.get_gtt.return_value = active_gtt

        with pytest.raises(GTTExecutionError) as exc_info:
            await executor.retry_failed_gtt(1)

        assert "can only retry failed" in str(exc_info.value).lower()


class TestStatistics:
    """Test statistics tracking."""

    @pytest.mark.asyncio
    async def test_stats_tracking(self, executor, sample_gtt, mock_risk_manager):
        """Test statistics are tracked."""
        from src.trader.risk.manager import OrderValidation

        # Successful execution
        mock_risk_manager.validate_order.return_value = OrderValidation(approved=True)
        await executor.execute_gtt(sample_gtt, 2495.0)

        # Failed execution (risk rejection)
        sample_gtt.id = 2
        mock_risk_manager.validate_order.return_value = OrderValidation(
            approved=False,
            reason="Test rejection"
        )

        try:
            await executor.execute_gtt(sample_gtt, 2495.0)
        except GTTExecutionError:
            pass

        stats = executor.get_stats()

        assert stats['executions_attempted'] == 2
        assert stats['executions_succeeded'] == 1
        assert stats['risk_rejections'] == 1
        assert stats['success_rate'] == 50.0
