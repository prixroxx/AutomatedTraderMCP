"""
Tests for GTT Monitor.

Tests cover:
- Monitor start/stop
- GTT checking loop
- Trigger detection
- Price caching
- Statistics tracking
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, time

from src.trader.gtt.monitor import GTTMonitor
from src.trader.api.models import GTTOrder, GTTStatus


@pytest.fixture
def mock_groww_client():
    """Mock Groww client."""
    client = Mock()
    client.get_ltp = AsyncMock(return_value=2495.0)
    return client


@pytest.fixture
def mock_storage():
    """Mock GTT storage."""
    storage = Mock()
    storage.get_active_gtts = AsyncMock(return_value=[])
    return storage


@pytest.fixture
def mock_executor():
    """Mock GTT executor."""
    executor = Mock()
    executor.execute_gtt = AsyncMock()
    return executor


@pytest.fixture
def monitor(mock_groww_client, mock_storage, mock_executor):
    """Create test monitor."""
    return GTTMonitor(
        mock_groww_client,
        mock_storage,
        mock_executor,
        check_interval=1  # Short interval for testing
    )


@pytest.fixture
def sample_gtt_buy():
    """Create sample BUY GTT."""
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


@pytest.fixture
def sample_gtt_sell():
    """Create sample SELL GTT."""
    return GTTOrder(
        id=2,
        symbol="TCS",
        exchange="NSE",
        trigger_price=3500.0,
        order_type="LIMIT",
        action="SELL",
        quantity=1,
        limit_price=3510.0,
        status=GTTStatus.ACTIVE.value,
        created_at=datetime.now()
    )


class TestMonitorLifecycle:
    """Test monitor start/stop."""

    @pytest.mark.asyncio
    async def test_start_monitor(self, monitor):
        """Test starting monitor."""
        await monitor.start()

        assert monitor.is_running() is True
        assert monitor._monitor_task is not None

        # Stop to clean up
        await monitor.stop()

    @pytest.mark.asyncio
    async def test_stop_monitor(self, monitor):
        """Test stopping monitor."""
        await monitor.start()
        await monitor.stop()

        assert monitor.is_running() is False

    @pytest.mark.asyncio
    async def test_start_already_running(self, monitor):
        """Test starting already running monitor is idempotent."""
        await monitor.start()
        await monitor.start()  # Should not raise

        assert monitor.is_running() is True

        await monitor.stop()

    @pytest.mark.asyncio
    async def test_pause_resume(self, monitor):
        """Test pausing and resuming monitor."""
        await monitor.start()

        monitor.pause()
        assert monitor.is_paused() is True

        monitor.resume()
        assert monitor.is_paused() is False

        await monitor.stop()


class TestTriggerDetection:
    """Test trigger condition detection."""

    def test_should_trigger_buy_below_trigger(self, monitor, sample_gtt_buy):
        """Test BUY GTT triggers when LTP <= trigger price."""
        # LTP below trigger price - should trigger
        assert monitor._should_trigger(sample_gtt_buy, 2490.0) is True

        # LTP at trigger price - should trigger
        assert monitor._should_trigger(sample_gtt_buy, 2500.0) is True

        # LTP above trigger price - should not trigger
        assert monitor._should_trigger(sample_gtt_buy, 2510.0) is False

    def test_should_trigger_sell_above_trigger(self, monitor, sample_gtt_sell):
        """Test SELL GTT triggers when LTP >= trigger price."""
        # LTP above trigger price - should trigger
        assert monitor._should_trigger(sample_gtt_sell, 3510.0) is True

        # LTP at trigger price - should trigger
        assert monitor._should_trigger(sample_gtt_sell, 3500.0) is True

        # LTP below trigger price - should not trigger
        assert monitor._should_trigger(sample_gtt_sell, 3490.0) is False


class TestGTTChecking:
    """Test GTT checking logic."""

    @pytest.mark.asyncio
    async def test_check_no_active_gtts(self, monitor, mock_storage):
        """Test checking when no active GTTs."""
        mock_storage.get_active_gtts.return_value = []

        await monitor._check_gtts()

        assert monitor.stats['checks_performed'] == 1

    @pytest.mark.asyncio
    async def test_check_with_trigger(self, monitor, mock_storage, mock_groww_client, mock_executor, sample_gtt_buy):
        """Test checking GTT that should trigger."""
        mock_storage.get_active_gtts.return_value = [sample_gtt_buy]

        # Set LTP below trigger price (should trigger BUY)
        mock_groww_client.get_ltp.return_value = 2490.0

        await monitor._check_gtts()

        # Verify executor called
        mock_executor.execute_gtt.assert_called_once()
        assert monitor.stats['gtts_triggered'] == 1

    @pytest.mark.asyncio
    async def test_check_without_trigger(self, monitor, mock_storage, mock_groww_client, mock_executor, sample_gtt_buy):
        """Test checking GTT that should not trigger."""
        mock_storage.get_active_gtts.return_value = [sample_gtt_buy]

        # Set LTP above trigger price (should not trigger BUY)
        mock_groww_client.get_ltp.return_value = 2510.0

        await monitor._check_gtts()

        # Verify executor NOT called
        mock_executor.execute_gtt.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_multiple_gtts_same_symbol(self, monitor, mock_storage, mock_groww_client, mock_executor):
        """Test checking multiple GTTs for same symbol."""
        gtt1 = GTTOrder(
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

        gtt2 = GTTOrder(
            id=2,
            symbol="RELIANCE",
            exchange="NSE",
            trigger_price=2480.0,
            order_type="LIMIT",
            action="BUY",
            quantity=1,
            limit_price=2470.0,
            status=GTTStatus.ACTIVE.value,
            created_at=datetime.now()
        )

        mock_storage.get_active_gtts.return_value = [gtt1, gtt2]
        mock_groww_client.get_ltp.return_value = 2485.0  # Triggers gtt2 only

        await monitor._check_gtts()

        # Should call LTP only once (grouped by symbol)
        assert mock_groww_client.get_ltp.call_count == 1

        # Should trigger only gtt2
        assert mock_executor.execute_gtt.call_count == 1


class TestPriceCaching:
    """Test price caching."""

    @pytest.mark.asyncio
    async def test_price_caching(self, monitor, mock_groww_client):
        """Test LTP caching reduces API calls."""
        # First call - should hit API
        ltp1 = await monitor._get_ltp("RELIANCE", "NSE")

        # Second call within TTL - should use cache
        ltp2 = await monitor._get_ltp("RELIANCE", "NSE")

        assert ltp1 == ltp2
        assert mock_groww_client.get_ltp.call_count == 1  # Only called once

    @pytest.mark.asyncio
    async def test_cache_expiry(self, monitor, mock_groww_client):
        """Test cache expires after TTL."""
        # Set very short TTL for testing
        monitor._cache_ttl = 0.1

        # First call
        await monitor._get_ltp("RELIANCE", "NSE")

        # Wait for cache to expire
        await asyncio.sleep(0.2)

        # Second call - should hit API again
        await monitor._get_ltp("RELIANCE", "NSE")

        assert mock_groww_client.get_ltp.call_count == 2

    def test_clear_price_cache(self, monitor):
        """Test clearing price cache."""
        monitor._price_cache["RELIANCE:NSE"] = (2500.0, datetime.now())

        monitor.clear_price_cache()

        assert len(monitor._price_cache) == 0


class TestGrouping:
    """Test GTT grouping."""

    def test_group_by_symbol(self, monitor, sample_gtt_buy, sample_gtt_sell):
        """Test grouping GTTs by symbol."""
        gtt_reliance_2 = GTTOrder(
            id=3,
            symbol="RELIANCE",
            exchange="NSE",
            trigger_price=2600.0,
            order_type="LIMIT",
            action="SELL",
            quantity=1,
            limit_price=2610.0,
            status=GTTStatus.ACTIVE.value,
            created_at=datetime.now()
        )

        gtts = [sample_gtt_buy, sample_gtt_sell, gtt_reliance_2]

        grouped = monitor._group_by_symbol(gtts)

        assert len(grouped) == 2  # RELIANCE and TCS
        assert len(grouped["RELIANCE:NSE"]) == 2
        assert len(grouped["TCS:NSE"]) == 1


class TestTradingHours:
    """Test trading hours check."""

    def test_is_trading_hours_weekday(self, monitor):
        """Test trading hours on weekday."""
        with patch('src.trader.gtt.monitor.datetime') as mock_datetime:
            # Monday at 10:00 AM
            mock_datetime.now.return_value = datetime(2024, 1, 1, 10, 0)  # Monday
            mock_datetime.return_value.weekday.return_value = 0  # Monday

            result = monitor._is_trading_hours()

            # Should be True (between 9:15 AM and 3:30 PM)
            assert result is True

    def test_is_trading_hours_weekend(self, monitor):
        """Test trading hours on weekend."""
        with patch('src.trader.gtt.monitor.datetime') as mock_datetime:
            # Saturday at 10:00 AM
            mock_datetime.now.return_value = datetime(2024, 1, 6, 10, 0)  # Saturday
            mock_datetime.return_value.weekday.return_value = 5  # Saturday

            result = monitor._is_trading_hours()

            # Should be False (weekend)
            assert result is False


class TestManualCheck:
    """Test manual GTT check."""

    @pytest.mark.asyncio
    async def test_check_now(self, monitor, mock_storage):
        """Test manual GTT check."""
        mock_storage.get_active_gtts.return_value = []

        await monitor.check_now()

        assert monitor.stats['checks_performed'] == 1


class TestErrorHandling:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_api_error_handling(self, monitor, mock_storage, mock_groww_client, mock_executor, sample_gtt_buy):
        """Test handling API errors gracefully."""
        from src.trader.api.exceptions import DataFetchError

        mock_storage.get_active_gtts.return_value = [sample_gtt_buy]
        mock_groww_client.get_ltp.side_effect = DataFetchError("API error")

        # Should not raise
        await monitor._check_gtts()

        assert monitor.stats['api_errors'] == 1

    @pytest.mark.asyncio
    async def test_execution_error_handling(self, monitor, mock_storage, mock_groww_client, mock_executor, sample_gtt_buy):
        """Test handling execution errors gracefully."""
        from src.trader.api.exceptions import GTTExecutionError

        mock_storage.get_active_gtts.return_value = [sample_gtt_buy]
        mock_groww_client.get_ltp.return_value = 2490.0  # Should trigger
        mock_executor.execute_gtt.side_effect = GTTExecutionError("Execution failed", gtt_id=1)

        # Should not raise
        await monitor._check_gtts()

        assert monitor.stats['trigger_failures'] == 1


class TestStatistics:
    """Test statistics tracking."""

    @pytest.mark.asyncio
    async def test_get_stats(self, monitor, mock_storage, sample_gtt_buy):
        """Test getting statistics."""
        await monitor.start()

        mock_storage.get_active_gtts.return_value = [sample_gtt_buy]

        # Wait for at least one check
        await asyncio.sleep(1.5)

        await monitor.stop()

        stats = monitor.get_stats()

        assert 'checks_performed' in stats
        assert 'is_running' in stats
        assert 'uptime_seconds' in stats
        assert stats['is_running'] is False
