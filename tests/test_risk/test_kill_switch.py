"""
Tests for Kill Switch.

Tests cover:
- Activation/deactivation
- Condition monitoring
- Cooldown period
- Approval code validation
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch

from src.trader.risk.kill_switch import KillSwitch, KillSwitchCondition
from src.trader.api.exceptions import KillSwitchActive
from src.trader.api.models import RiskMetrics


@pytest.fixture
def mock_config():
    """Mock configuration."""
    config = Mock()
    config.get.side_effect = lambda key, default=None: {
        'kill_switch': {
            'consecutive_loss_threshold': 5,
            'api_error_rate_threshold': 0.3,
            'network_timeout_seconds': 60,
            'check_interval_seconds': 30,
            'recovery_protocol': {
                'cooldown_period_minutes': 60,
                'approval_code': 'TEST_CODE_123'
            }
        }
    }.get(key, default)
    config.hard_limits = {
        'MAX_DAILY_LOSS_HARD': 5000
    }
    return config


@pytest.fixture
def mock_risk_manager():
    """Mock risk manager."""
    manager = Mock()
    manager.get_status = AsyncMock(return_value=RiskMetrics(
        daily_pnl=0,
        open_positions=0,
        max_positions=3,
        used_capital=0,
        available_capital=50000,
        daily_loss_limit=2000,
        daily_order_count=0,
        max_daily_orders=15,
        kill_switch_active=False,
        is_healthy=True,
        warnings=[]
    ))
    return manager


@pytest.fixture
def kill_switch(mock_risk_manager, mock_config):
    """Create test kill switch."""
    with patch('src.trader.risk.kill_switch.get_config', return_value=mock_config):
        return KillSwitch(mock_risk_manager, config=mock_config)


class TestKillSwitchInitialization:
    """Test kill switch initialization."""

    def test_kill_switch_creation(self, kill_switch):
        """Test kill switch is created with correct config."""
        assert kill_switch.daily_loss_threshold == 5000
        assert kill_switch.consecutive_loss_threshold == 5
        assert kill_switch.api_error_rate_threshold == 0.3
        assert kill_switch.cooldown_minutes == 60
        assert kill_switch.approval_code == 'TEST_CODE_123'
        assert kill_switch._active is False


class TestActivation:
    """Test kill switch activation."""

    def test_activate_manual(self, kill_switch):
        """Test manual activation."""
        kill_switch.activate(
            reason="Manual trigger for testing",
            condition=KillSwitchCondition.MANUAL_TRIGGER
        )

        assert kill_switch._active is True
        assert kill_switch._reason == "Manual trigger for testing"
        assert kill_switch._activated_at is not None
        assert kill_switch.stats['manual_triggers'] == 1

    def test_activate_idempotent(self, kill_switch):
        """Test activating already active switch is idempotent."""
        kill_switch.activate("First activation")
        initial_time = kill_switch._activated_at

        kill_switch.activate("Second activation")

        # Should still be first activation
        assert kill_switch._activated_at == initial_time
        assert kill_switch._reason == "First activation"

    def test_check_before_order_active(self, kill_switch):
        """Test checking before order when active raises exception."""
        kill_switch.activate("Testing")

        with pytest.raises(KillSwitchActive) as exc_info:
            kill_switch.check_before_order()

        assert "Testing" in str(exc_info.value)

    def test_check_before_order_inactive(self, kill_switch):
        """Test checking before order when inactive passes."""
        # Should not raise
        kill_switch.check_before_order()


class TestDeactivation:
    """Test kill switch deactivation."""

    def test_deactivate_wrong_code(self, kill_switch):
        """Test deactivation with wrong approval code fails."""
        kill_switch.activate("Testing")

        with pytest.raises(KillSwitchActive) as exc_info:
            kill_switch.deactivate("WRONG_CODE")

        assert "Invalid approval code" in str(exc_info.value)
        assert kill_switch._active is True

    def test_deactivate_during_cooldown(self, kill_switch):
        """Test deactivation during cooldown fails."""
        kill_switch.activate("Testing")
        kill_switch._activated_at = datetime.now()  # Just activated

        with pytest.raises(KillSwitchActive) as exc_info:
            kill_switch.deactivate("TEST_CODE_123")

        assert "Cooldown period not elapsed" in str(exc_info.value)
        assert kill_switch._active is True

    def test_deactivate_after_cooldown(self, kill_switch):
        """Test successful deactivation after cooldown."""
        kill_switch.activate("Testing")
        # Simulate cooldown elapsed
        kill_switch._activated_at = datetime.now() - timedelta(minutes=61)

        result = kill_switch.deactivate("TEST_CODE_123")

        assert result is True
        assert kill_switch._active is False
        assert kill_switch._reason is None
        assert kill_switch.stats['deactivations'] == 1

    def test_deactivate_when_not_active(self, kill_switch):
        """Test deactivating when not active."""
        result = kill_switch.deactivate("TEST_CODE_123")

        assert result is False


class TestConditionMonitoring:
    """Test condition monitoring."""

    @pytest.mark.asyncio
    async def test_daily_loss_limit_trigger(self, kill_switch, mock_risk_manager):
        """Test kill switch triggers on daily loss limit."""
        # Mock risk status with excessive loss
        mock_risk_manager.get_status = AsyncMock(return_value=RiskMetrics(
            daily_pnl=-5500,  # Exceeds 5000 limit
            open_positions=1,
            max_positions=3,
            used_capital=5000,
            available_capital=45000,
            daily_loss_limit=2000,
            daily_order_count=5,
            max_daily_orders=15,
            kill_switch_active=False,
            is_healthy=False,
            warnings=["Daily loss exceeded"]
        ))

        await kill_switch._check_conditions()

        assert kill_switch._active is True
        assert "Daily loss limit breached" in kill_switch._reason
        assert kill_switch.stats['auto_triggers'] == 1

    @pytest.mark.asyncio
    async def test_consecutive_losses_trigger(self, kill_switch):
        """Test kill switch triggers on consecutive losses."""
        # Record 5 consecutive losses
        for _ in range(5):
            kill_switch.record_trade_result(-100)

        await kill_switch._check_conditions()

        assert kill_switch._active is True
        assert "Consecutive loss limit breached" in kill_switch._reason

    @pytest.mark.asyncio
    async def test_consecutive_losses_reset_on_profit(self, kill_switch):
        """Test consecutive losses reset on profitable trade."""
        # Record 3 losses
        for _ in range(3):
            kill_switch.record_trade_result(-100)

        assert kill_switch._consecutive_losses == 3

        # Record profit
        kill_switch.record_trade_result(50)

        assert kill_switch._consecutive_losses == 0

    @pytest.mark.asyncio
    async def test_api_error_rate_trigger(self, kill_switch):
        """Test kill switch triggers on high API error rate."""
        # Record 30 errors out of 50 calls (60% error rate > 30% threshold)
        for _ in range(30):
            kill_switch.record_api_call(success=False)
        for _ in range(20):
            kill_switch.record_api_call(success=True)

        await kill_switch._check_conditions()

        assert kill_switch._active is True
        assert "API error rate exceeded" in kill_switch._reason

    @pytest.mark.asyncio
    async def test_network_failure_trigger(self, kill_switch):
        """Test kill switch triggers on network failure."""
        # Simulate network failure starting 70 seconds ago
        kill_switch._network_failure_start = datetime.now() - timedelta(seconds=70)

        await kill_switch._check_conditions()

        assert kill_switch._active is True
        assert "Network failure duration exceeded" in kill_switch._reason


class TestConditionTracking:
    """Test condition tracking."""

    def test_record_api_call(self, kill_switch):
        """Test recording API call results."""
        kill_switch.record_api_call(success=True)
        kill_switch.record_api_call(success=False)

        assert len(kill_switch._api_call_history) == 2

    def test_calculate_api_error_rate(self, kill_switch):
        """Test calculating API error rate."""
        # Record 7 errors out of 10 calls
        for _ in range(7):
            kill_switch.record_api_call(success=False)
        for _ in range(3):
            kill_switch.record_api_call(success=True)

        error_rate = kill_switch._calculate_api_error_rate()

        assert error_rate == 0.7  # 70% error rate

    def test_record_network_failure(self, kill_switch):
        """Test recording network failure."""
        # Start failure
        kill_switch.record_network_failure(is_failure=True)
        assert kill_switch._network_failure_start is not None

        # End failure
        kill_switch.record_network_failure(is_failure=False)
        assert kill_switch._network_failure_start is None


class TestMonitoring:
    """Test monitoring loop."""

    @pytest.mark.asyncio
    async def test_start_monitoring(self, kill_switch):
        """Test starting monitoring."""
        await kill_switch.start_monitoring()

        assert kill_switch._monitoring is True
        assert kill_switch._monitor_task is not None

        # Stop monitoring
        await kill_switch.stop_monitoring()

    @pytest.mark.asyncio
    async def test_stop_monitoring(self, kill_switch):
        """Test stopping monitoring."""
        await kill_switch.start_monitoring()
        await kill_switch.stop_monitoring()

        assert kill_switch._monitoring is False

    @pytest.mark.asyncio
    async def test_monitoring_idempotent(self, kill_switch):
        """Test starting monitoring multiple times is idempotent."""
        await kill_switch.start_monitoring()
        await kill_switch.start_monitoring()

        # Should only have one monitoring task
        assert kill_switch._monitoring is True

        await kill_switch.stop_monitoring()


class TestStatus:
    """Test status reporting."""

    def test_get_status_inactive(self, kill_switch):
        """Test getting status when inactive."""
        status = kill_switch.get_status()

        assert status['active'] is False
        assert status['reason'] is None
        assert status['monitoring'] is False

    def test_get_status_active(self, kill_switch):
        """Test getting status when active."""
        kill_switch.activate("Testing")

        status = kill_switch.get_status()

        assert status['active'] is True
        assert status['reason'] == "Testing"
        assert status['activated_at'] is not None
        assert 'elapsed_seconds' in status
        assert 'cooldown_remaining_seconds' in status

    def test_get_stats(self, kill_switch):
        """Test getting statistics."""
        kill_switch.activate("Test 1")
        kill_switch._activated_at = datetime.now() - timedelta(minutes=61)
        kill_switch.deactivate("TEST_CODE_123")

        kill_switch.activate("Test 2")

        stats = kill_switch.get_stats()

        assert stats['activations'] == 2
        assert stats['deactivations'] == 1
        assert 'current_status' in stats


class TestUtilities:
    """Test utility methods."""

    def test_is_active(self, kill_switch):
        """Test is_active method."""
        assert kill_switch.is_active() is False

        kill_switch.activate("Testing")
        assert kill_switch.is_active() is True

    def test_reset_for_testing(self, kill_switch):
        """Test reset for testing."""
        kill_switch.activate("Testing")
        kill_switch.record_trade_result(-100)
        kill_switch.record_api_call(success=False)

        kill_switch.reset_for_testing()

        assert kill_switch._active is False
        assert kill_switch._consecutive_losses == 0
        assert len(kill_switch._api_call_history) == 0
