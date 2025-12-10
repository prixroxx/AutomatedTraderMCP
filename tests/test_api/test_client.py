"""
Tests for Groww API Client.

Tests cover:
- Paper mode behavior
- Order validation
- Rate limiting
- Error handling
- Market data fetching
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from src.trader.api.client import GrowwClient
from src.trader.api.models import Order, Quote, Position, OrderType, TransactionType
from src.trader.api.exceptions import (
    OrderError, InvalidOrderError, RateLimitExceeded,
    KillSwitchActive, AuthenticationError
)


@pytest.fixture
def mock_config():
    """Mock configuration."""
    config = Mock()
    config.is_paper_mode.return_value = True
    config.get.side_effect = lambda key, default=None: {
        'api.rate_limits': {
            'orders_per_second': 10,
            'live_data_per_second': 8,
            'non_trading_per_second': 15
        },
        'risk.max_portfolio_value': 50000,
        'risk.max_position_size': 5000
    }.get(key, default)
    config.hard_limits = {
        'MAX_SINGLE_ORDER_VALUE': 10000,
        'MAX_DAILY_ORDERS': 15,
        'FORBIDDEN_SEGMENTS': ['FNO'],
        'FORBIDDEN_PRODUCTS': ['MIS']
    }
    return config


@pytest.fixture
def mock_auth_manager():
    """Mock authentication manager."""
    with patch('src.trader.api.client.AuthManager') as mock:
        instance = mock.return_value
        instance.get_access_token = AsyncMock(return_value='test_token')
        instance.get_token_info.return_value = {
            'has_token': True,
            'is_valid': True
        }
        yield instance


@pytest.fixture
async def client(mock_config, mock_auth_manager):
    """Create test client."""
    with patch('src.trader.api.client.get_config', return_value=mock_config):
        client = GrowwClient(api_key='test_key', secret='test_secret', config=mock_config)

        # Mock the GrowwAPI
        client._api = Mock()
        client._initialized = True

        yield client


class TestClientInitialization:
    """Test client initialization."""

    def test_client_creation(self, mock_config):
        """Test client is created with correct defaults."""
        with patch('src.trader.api.client.get_config', return_value=mock_config):
            with patch('src.trader.api.client.AuthManager'):
                client = GrowwClient(api_key='test_key', secret='test_secret')

                assert client._paper_mode is True
                assert client._initialized is False
                assert client.stats['orders_placed'] == 0

    @pytest.mark.asyncio
    async def test_initialize_success(self, mock_config, mock_auth_manager):
        """Test successful initialization."""
        with patch('src.trader.api.client.get_config', return_value=mock_config):
            client = GrowwClient(api_key='test_key', secret='test_secret', config=mock_config)

            with patch('src.trader.api.client.GrowwAPI') as mock_api:
                await client.initialize()

                assert client._initialized is True
                mock_auth_manager.get_access_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_failure(self, mock_config):
        """Test initialization failure."""
        with patch('src.trader.api.client.get_config', return_value=mock_config):
            with patch('src.trader.api.client.AuthManager') as mock_auth:
                instance = mock_auth.return_value
                instance.get_access_token = AsyncMock(side_effect=Exception("Auth failed"))

                client = GrowwClient(api_key='test_key', secret='test_secret', config=mock_config)

                with pytest.raises(AuthenticationError):
                    await client.initialize()


class TestPaperMode:
    """Test paper trading mode."""

    @pytest.mark.asyncio
    async def test_place_order_paper_mode(self, client):
        """Test order placement in paper mode doesn't hit API."""
        order = await client.place_order(
            symbol='RELIANCE',
            exchange='NSE',
            transaction_type='BUY',
            quantity=1,
            order_type='LIMIT',
            price=2500
        )

        # Verify order returned
        assert order.order_id.startswith('PAPER_')
        assert order.symbol == 'RELIANCE'
        assert order.quantity == 1
        assert order.status == 'PENDING'
        assert 'PAPER MODE' in order.message

        # Verify API was NOT called
        assert not client._api.place_order.called

        # Verify stats
        assert client.stats['paper_mode_orders'] == 1

    @pytest.mark.asyncio
    async def test_cancel_order_paper_mode(self, client):
        """Test order cancellation in paper mode."""
        result = await client.cancel_order('PAPER_123')

        assert result is True
        assert not client._api.cancel_order.called

    @pytest.mark.asyncio
    async def test_get_positions_paper_mode(self, client):
        """Test getting positions in paper mode returns empty."""
        positions = await client.get_positions()

        assert positions == []
        assert not client._api.get_positions.called


class TestOrderValidation:
    """Test order validation."""

    @pytest.mark.asyncio
    async def test_validate_empty_symbol(self, client):
        """Test empty symbol raises error."""
        with pytest.raises(InvalidOrderError) as exc_info:
            await client.place_order(
                symbol='',
                exchange='NSE',
                transaction_type='BUY',
                quantity=1,
                order_type='LIMIT',
                price=100
            )

        assert 'Symbol cannot be empty' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validate_negative_quantity(self, client):
        """Test negative quantity raises error."""
        with pytest.raises(InvalidOrderError) as exc_info:
            await client.place_order(
                symbol='RELIANCE',
                exchange='NSE',
                transaction_type='BUY',
                quantity=-1,
                order_type='LIMIT',
                price=100
            )

        assert 'positive' in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_validate_limit_order_without_price(self, client):
        """Test LIMIT order without price raises error."""
        with pytest.raises(InvalidOrderError) as exc_info:
            await client.place_order(
                symbol='RELIANCE',
                exchange='NSE',
                transaction_type='BUY',
                quantity=1,
                order_type='LIMIT',
                price=None
            )

        assert 'price' in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_validate_forbidden_segment(self, client):
        """Test forbidden segment raises error."""
        with pytest.raises(InvalidOrderError) as exc_info:
            await client.place_order(
                symbol='RELIANCE',
                exchange='NSE',
                transaction_type='BUY',
                quantity=1,
                order_type='LIMIT',
                price=100,
                segment='FNO'
            )

        assert 'forbidden' in str(exc_info.value).lower()
        assert 'FNO' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validate_forbidden_product(self, client):
        """Test forbidden product raises error."""
        with pytest.raises(InvalidOrderError) as exc_info:
            await client.place_order(
                symbol='RELIANCE',
                exchange='NSE',
                transaction_type='BUY',
                quantity=1,
                order_type='LIMIT',
                price=100,
                product='MIS'
            )

        assert 'forbidden' in str(exc_info.value).lower()
        assert 'MIS' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validate_exceeds_hard_limit(self, client):
        """Test order exceeding hard limit raises error."""
        with pytest.raises(InvalidOrderError) as exc_info:
            await client.place_order(
                symbol='RELIANCE',
                exchange='NSE',
                transaction_type='BUY',
                quantity=100,
                order_type='LIMIT',
                price=500  # 100 * 500 = 50000 > 10000 limit
            )

        assert 'hard limit' in str(exc_info.value).lower()


class TestRateLimiting:
    """Test rate limiting."""

    @pytest.mark.asyncio
    async def test_rate_limiter_applied(self, client, mock_config):
        """Test rate limiter is applied to API calls."""
        # Disable paper mode for this test
        client._paper_mode = False

        # Mock API response
        client._api.place_order = Mock(return_value={
            'order_id': 'TEST123',
            'symbol': 'RELIANCE',
            'quantity': 1,
            'status': 'PENDING',
            'transaction_type': 'BUY',
            'order_type': 'LIMIT',
            'exchange': 'NSE'
        })

        # Place multiple orders rapidly
        for _ in range(3):
            await client.place_order(
                symbol='RELIANCE',
                exchange='NSE',
                transaction_type='BUY',
                quantity=1,
                order_type='LIMIT',
                price=100
            )

        # Verify rate limiter tracked calls
        assert client.rate_limiter.stats['orders']['total'] >= 3


class TestMarketData:
    """Test market data methods."""

    @pytest.mark.asyncio
    async def test_get_quote(self, client):
        """Test getting quote."""
        # Mock API response
        client._api.get_quote = Mock(return_value={
            'ltp': 2500.50,
            'open': 2480.00,
            'high': 2520.00,
            'low': 2475.00,
            'close': 2490.00,
            'volume': 1000000
        })

        quote = await client.get_quote('RELIANCE', 'NSE')

        assert quote.symbol == 'RELIANCE'
        assert quote.exchange == 'NSE'
        assert quote.ltp == 2500.50
        assert client.stats['quotes_fetched'] == 1

    @pytest.mark.asyncio
    async def test_get_ltp(self, client):
        """Test getting LTP."""
        client._api.get_ltp = Mock(return_value={'ltp': 2500.50})

        ltp = await client.get_ltp('RELIANCE', 'NSE')

        assert ltp == 2500.50


class TestErrorHandling:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, client):
        """Test API call retries on failure."""
        # Disable paper mode
        client._paper_mode = False

        # Mock API to fail twice then succeed
        call_count = [0]

        def mock_place_order(**kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("Temporary error")
            return {
                'order_id': 'TEST123',
                'symbol': 'RELIANCE',
                'quantity': 1,
                'status': 'PENDING',
                'transaction_type': 'BUY',
                'order_type': 'LIMIT',
                'exchange': 'NSE'
            }

        client._api.place_order = Mock(side_effect=mock_place_order)

        # Should succeed after retries
        order = await client.place_order(
            symbol='RELIANCE',
            exchange='NSE',
            transaction_type='BUY',
            quantity=1,
            order_type='LIMIT',
            price=100
        )

        assert order.order_id == 'TEST123'
        assert call_count[0] == 3  # Failed twice, succeeded third time

    @pytest.mark.asyncio
    async def test_no_retry_on_invalid_order(self, client):
        """Test no retry on InvalidOrderError."""
        # Should immediately raise without retrying
        with pytest.raises(InvalidOrderError):
            await client.place_order(
                symbol='',
                exchange='NSE',
                transaction_type='BUY',
                quantity=1,
                order_type='LIMIT',
                price=100
            )


class TestClientStats:
    """Test client statistics."""

    @pytest.mark.asyncio
    async def test_get_stats(self, client):
        """Test getting client stats."""
        # Place a paper mode order
        await client.place_order(
            symbol='RELIANCE',
            exchange='NSE',
            transaction_type='BUY',
            quantity=1,
            order_type='LIMIT',
            price=100
        )

        stats = client.get_stats()

        assert stats['paper_mode'] is True
        assert stats['initialized'] is True
        assert stats['paper_mode_orders'] == 1
        assert 'rate_limiter' in stats
        assert 'token_info' in stats
