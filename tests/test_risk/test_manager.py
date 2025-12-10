"""
Tests for Risk Manager.

Tests cover:
- Order validation pipeline
- Position limits
- Daily loss limits
- Order count limits
- P&L tracking
"""

import pytest
from datetime import date, datetime
from unittest.mock import Mock, AsyncMock, patch

from src.trader.risk.manager import RiskManager, OrderValidation
from src.trader.api.models import Position, Order


@pytest.fixture
def mock_config():
    """Mock configuration."""
    config = Mock()
    config.get.side_effect = lambda key, default=None: {
        'risk': {
            'max_portfolio_value': 50000,
            'max_position_size': 5000,
            'max_daily_loss': 2000,
            'max_open_positions': 3
        }
    }.get(key, default)
    config.hard_limits = {
        'MAX_SINGLE_ORDER_VALUE': 10000,
        'MAX_DAILY_ORDERS': 15,
        'MAX_DAILY_LOSS_HARD': 5000,
        'FORBIDDEN_SEGMENTS': ['FNO'],
        'FORBIDDEN_PRODUCTS': ['MIS']
    }
    return config


@pytest.fixture
def mock_groww_client():
    """Mock Groww client."""
    client = Mock()
    client.get_positions = AsyncMock(return_value=[])
    return client


@pytest.fixture
def risk_manager(mock_groww_client, mock_config):
    """Create test risk manager."""
    with patch('src.trader.risk.manager.get_config', return_value=mock_config):
        return RiskManager(mock_groww_client, config=mock_config)


class TestRiskManagerInitialization:
    """Test risk manager initialization."""

    def test_manager_creation(self, risk_manager):
        """Test manager is created with correct limits."""
        assert risk_manager.max_portfolio_value == 50000
        assert risk_manager.max_position_size == 5000
        assert risk_manager.max_daily_loss == 2000
        assert risk_manager.max_open_positions == 3
        assert risk_manager.max_single_order_value == 10000
        assert risk_manager.max_daily_orders == 15


class TestOrderValidation:
    """Test order validation."""

    @pytest.mark.asyncio
    async def test_validate_normal_order(self, risk_manager):
        """Test normal order passes validation."""
        result = await risk_manager.validate_order(
            symbol='RELIANCE',
            quantity=1,
            price=2500,
            transaction_type='BUY'
        )

        assert result.approved is True
        assert result.reason is None

    @pytest.mark.asyncio
    async def test_validate_exceeds_single_order_limit(self, risk_manager):
        """Test order exceeding single order limit is rejected."""
        result = await risk_manager.validate_order(
            symbol='RELIANCE',
            quantity=100,
            price=200,  # 100 * 200 = 20,000 > 10,000 limit
            transaction_type='BUY'
        )

        assert result.approved is False
        assert 'hard limit' in result.reason.lower()
        assert result.limit_type == 'max_single_order_value'

    @pytest.mark.asyncio
    async def test_validate_exceeds_position_size(self, risk_manager):
        """Test order exceeding position size is rejected."""
        result = await risk_manager.validate_order(
            symbol='RELIANCE',
            quantity=10,
            price=600,  # 10 * 600 = 6,000 > 5,000 position size
            transaction_type='BUY'
        )

        assert result.approved is False
        assert 'position size' in result.reason.lower()
        assert result.limit_type == 'max_position_size'

    @pytest.mark.asyncio
    async def test_validate_sell_order_ignores_position_limit(self, risk_manager):
        """Test SELL orders don't check position size limit."""
        result = await risk_manager.validate_order(
            symbol='RELIANCE',
            quantity=10,
            price=600,  # Would exceed position size for BUY
            transaction_type='SELL'
        )

        # Should pass because SELL doesn't check position size
        # (might still fail on single order limit if total > 10k)
        assert result.approved is True

    @pytest.mark.asyncio
    async def test_validate_forbidden_segment(self, risk_manager):
        """Test forbidden segment is rejected."""
        result = await risk_manager.validate_order(
            symbol='RELIANCE',
            quantity=1,
            price=100,
            transaction_type='BUY',
            segment='FNO'
        )

        assert result.approved is False
        assert 'forbidden' in result.reason.lower()
        assert 'FNO' in result.reason

    @pytest.mark.asyncio
    async def test_validate_forbidden_product(self, risk_manager):
        """Test forbidden product is rejected."""
        result = await risk_manager.validate_order(
            symbol='RELIANCE',
            quantity=1,
            price=100,
            transaction_type='BUY',
            product='MIS'
        )

        assert result.approved is False
        assert 'forbidden' in result.reason.lower()
        assert 'MIS' in result.reason


class TestDailyLimits:
    """Test daily limits."""

    @pytest.mark.asyncio
    async def test_daily_order_count_limit(self, risk_manager):
        """Test daily order count limit."""
        # Simulate 15 orders already placed today
        risk_manager._daily_order_count = 15

        result = await risk_manager.validate_order(
            symbol='RELIANCE',
            quantity=1,
            price=100,
            transaction_type='BUY'
        )

        assert result.approved is False
        assert 'daily order limit' in result.reason.lower()
        assert result.limit_type == 'max_daily_orders'

    @pytest.mark.asyncio
    async def test_daily_loss_soft_limit(self, risk_manager):
        """Test daily loss soft limit."""
        # Simulate daily loss of 2000 (at soft limit)
        risk_manager._daily_pnl = -2000

        result = await risk_manager.validate_order(
            symbol='RELIANCE',
            quantity=1,
            price=100,
            transaction_type='BUY'
        )

        assert result.approved is False
        assert 'daily loss limit' in result.reason.lower()

    @pytest.mark.asyncio
    async def test_daily_loss_hard_limit(self, risk_manager):
        """Test daily loss hard limit."""
        # Simulate daily loss of 5000 (at hard limit)
        risk_manager._daily_pnl = -5000

        result = await risk_manager.validate_order(
            symbol='RELIANCE',
            quantity=1,
            price=100,
            transaction_type='BUY'
        )

        assert result.approved is False
        assert 'hard daily loss' in result.reason.lower()
        assert 'KILL SWITCH' in result.reason


class TestPositionTracking:
    """Test position tracking."""

    @pytest.mark.asyncio
    async def test_max_open_positions_limit(self, risk_manager):
        """Test maximum open positions limit."""
        # Simulate 3 open positions
        risk_manager._open_positions = {
            'RELIANCE': Mock(),
            'TCS': Mock(),
            'INFY': Mock()
        }
        risk_manager._position_count = 3

        # Try to open a 4th position
        result = await risk_manager.validate_order(
            symbol='WIPRO',  # New position
            quantity=1,
            price=500,
            transaction_type='BUY'
        )

        assert result.approved is False
        assert 'maximum open positions' in result.reason.lower()

    @pytest.mark.asyncio
    async def test_add_to_existing_position_allowed(self, risk_manager):
        """Test adding to existing position is allowed."""
        # Simulate 3 open positions
        risk_manager._open_positions = {
            'RELIANCE': Mock(),
            'TCS': Mock(),
            'INFY': Mock()
        }
        risk_manager._position_count = 3

        # Try to add to existing position
        result = await risk_manager.validate_order(
            symbol='RELIANCE',  # Existing position
            quantity=1,
            price=2500,
            transaction_type='BUY'
        )

        # Should pass because we're not opening a new position
        assert result.approved is True


class TestDayRollover:
    """Test day rollover logic."""

    @pytest.mark.asyncio
    async def test_day_rollover_resets_counters(self, risk_manager):
        """Test day rollover resets daily counters."""
        # Set up previous day state
        yesterday = date(2024, 1, 1)
        risk_manager._current_day = yesterday
        risk_manager._daily_pnl = -1000
        risk_manager._daily_order_count = 10

        # Simulate new day
        with patch('src.trader.risk.manager.date') as mock_date:
            mock_date.today.return_value = date(2024, 1, 2)

            # Validate order should trigger rollover
            result = await risk_manager.validate_order(
                symbol='RELIANCE',
                quantity=1,
                price=100,
                transaction_type='BUY'
            )

            # Counters should be reset
            assert risk_manager._daily_pnl == 0
            assert risk_manager._daily_order_count == 0
            assert result.approved is True


class TestPnLTracking:
    """Test P&L tracking."""

    @pytest.mark.asyncio
    async def test_update_daily_pnl(self, risk_manager, mock_groww_client):
        """Test daily P&L update from positions."""
        # Mock positions with P&L
        mock_groww_client.get_positions = AsyncMock(return_value=[
            Position(
                symbol='RELIANCE',
                exchange='NSE',
                product='CNC',
                quantity=1,
                average_price=2500,
                pnl=100
            ),
            Position(
                symbol='TCS',
                exchange='NSE',
                product='CNC',
                quantity=1,
                average_price=3500,
                pnl=-50
            )
        ])

        daily_pnl = await risk_manager.update_daily_pnl()

        assert daily_pnl == 50  # 100 - 50
        assert risk_manager._daily_pnl == 50
        assert risk_manager._position_count == 2


class TestRiskStatus:
    """Test risk status."""

    @pytest.mark.asyncio
    async def test_get_status_healthy(self, risk_manager):
        """Test getting status when system is healthy."""
        risk_manager._daily_pnl = 500  # Profitable
        risk_manager._daily_order_count = 5
        risk_manager._position_count = 2

        status = await risk_manager.get_status()

        assert status.is_healthy is True
        assert len(status.warnings) == 0
        assert status.daily_pnl == 500
        assert status.daily_order_count == 5
        assert status.open_positions == 2

    @pytest.mark.asyncio
    async def test_get_status_warnings(self, risk_manager):
        """Test getting status with warnings."""
        # Set up warning conditions
        risk_manager._daily_pnl = -1800  # 90% of 2000 limit
        risk_manager._daily_order_count = 13  # 87% of 15 limit
        risk_manager._position_count = 3  # At max

        status = await risk_manager.get_status()

        assert status.is_healthy is False
        assert len(status.warnings) > 0


class TestRecordOrder:
    """Test order recording."""

    @pytest.mark.asyncio
    async def test_record_order(self, risk_manager):
        """Test recording an order."""
        order = Order(
            order_id='TEST123',
            symbol='RELIANCE',
            exchange='NSE',
            quantity=1,
            transaction_type='BUY',
            order_type='LIMIT',
            price=2500
        )

        await risk_manager.record_order(order)

        assert risk_manager._daily_order_count == 1
        assert len(risk_manager._daily_orders) == 1
        assert risk_manager._daily_orders[0].order_id == 'TEST123'


class TestStatistics:
    """Test statistics tracking."""

    @pytest.mark.asyncio
    async def test_stats_tracking(self, risk_manager):
        """Test statistics are tracked correctly."""
        # Approve an order
        await risk_manager.validate_order(
            symbol='RELIANCE',
            quantity=1,
            price=100,
            transaction_type='BUY'
        )

        # Reject an order
        await risk_manager.validate_order(
            symbol='RELIANCE',
            quantity=100,
            price=200,  # Exceeds limit
            transaction_type='BUY'
        )

        stats = risk_manager.get_stats()

        assert stats['orders_validated'] == 2
        assert stats['orders_approved'] == 1
        assert stats['orders_rejected'] == 1
        assert stats['approval_rate'] == 50.0
