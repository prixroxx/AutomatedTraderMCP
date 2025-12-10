"""
Groww API Client for trading operations.

This module provides a comprehensive interface to Groww API,
handling orders, market data, portfolio queries with full validation,
rate limiting, error handling, and paper trading support.
"""

import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from growwapi import GrowwAPI

from .auth import AuthManager
from .rate_limiter import RateLimiter
from .models import (
    Order, OrderStatusResponse, Quote, OHLC, Candle,
    HistoricalData, Position, Holding, AccountSummary,
    OrderType, TransactionType, Exchange, ProductType
)
from .exceptions import (
    GrowwAPIError, AuthenticationError, OrderError,
    InvalidOrderError, RateLimitExceeded, DataFetchError,
    NetworkError, TimeoutError, SymbolNotFoundError,
    MarketClosedError, InsufficientFundsError
)
from ..core.logging_config import get_logger
from ..core.config import get_config

logger = get_logger(__name__)


class GrowwClient:
    """
    Main Groww API client.

    Handles all interactions with Groww API including:
    - Order placement, modification, cancellation
    - Market data fetching (quotes, OHLC, historical data)
    - Portfolio queries (positions, holdings, account summary)
    - Paper trading mode
    - Rate limiting
    - Error handling and retries
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
        config = None
    ):
        """
        Initialize Groww API client.

        Args:
            api_key: Groww API key (from env if not provided)
            secret: Groww API secret (from env if not provided)
            config: Configuration object (loads default if not provided)
        """
        self.config = config or get_config()

        # Initialize authentication manager
        self.auth_manager = AuthManager(api_key, secret)

        # Initialize rate limiter from config
        rate_limits = self.config.get('api.rate_limits', {})
        self.rate_limiter = RateLimiter(
            orders_per_sec=rate_limits.get('orders_per_second', 10),
            data_per_sec=rate_limits.get('live_data_per_second', 8),
            non_trading_per_sec=rate_limits.get('non_trading_per_second', 15)
        )

        # Groww API instance (initialized in initialize())
        self._api: Optional[GrowwAPI] = None
        self._initialized = False

        # Paper trading mode
        self._paper_mode = self.config.is_paper_mode()

        # Statistics
        self.stats = {
            'orders_placed': 0,
            'orders_cancelled': 0,
            'quotes_fetched': 0,
            'api_errors': 0,
            'paper_mode_orders': 0
        }

        logger.info(
            "Groww client created",
            paper_mode=self._paper_mode,
            rate_limits=self.rate_limiter.limits
        )

    async def initialize(self) -> None:
        """
        Initialize the client by getting access token.

        MUST be called before using the client.

        Raises:
            AuthenticationError: If authentication fails
        """
        if self._initialized:
            logger.debug("Client already initialized")
            return

        try:
            logger.info("Initializing Groww client...")

            # Get access token
            access_token = await self.auth_manager.get_access_token()

            # Initialize Groww API
            self._api = GrowwAPI(
                access_token=access_token,
                api_key=self.auth_manager.api_key
            )

            self._initialized = True

            logger.info(
                "Groww client initialized successfully",
                paper_mode=self._paper_mode,
                token_info=self.auth_manager.get_token_info()
            )

        except Exception as e:
            logger.error(f"Failed to initialize Groww client: {e}")
            raise AuthenticationError(f"Client initialization failed: {str(e)}")

    def _ensure_initialized(self) -> None:
        """Ensure client is initialized before API calls."""
        if not self._initialized:
            raise GrowwAPIError(
                "Client not initialized. Call initialize() first."
            )

    # ==================== ORDER MANAGEMENT ====================

    async def place_order(
        self,
        symbol: str,
        exchange: str,
        transaction_type: str,
        quantity: int,
        order_type: str,
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        product: str = "CNC",
        segment: str = "CASH"
    ) -> Order:
        """
        Place order on Groww.

        CRITICAL: Checks paper mode BEFORE making API call.

        Args:
            symbol: Trading symbol (e.g., "RELIANCE")
            exchange: Exchange (NSE/BSE)
            transaction_type: BUY or SELL
            quantity: Number of shares
            order_type: LIMIT, MARKET, STOP_LOSS, STOP_LOSS_MARKET
            price: Limit price (required for LIMIT orders)
            trigger_price: Trigger price (required for SL orders)
            product: Product type (CNC/MIS/NRML)
            segment: Market segment (CASH/FNO)

        Returns:
            Order object with order details

        Raises:
            OrderError: If order placement fails
            InvalidOrderError: If order parameters are invalid
        """
        self._ensure_initialized()

        # Validate order parameters
        self._validate_order_params(
            symbol, quantity, order_type, price, trigger_price, product, segment
        )

        # Check hard limits
        order_value = quantity * (price or 0)
        max_single_order = self.config.hard_limits.get('MAX_SINGLE_ORDER_VALUE', 10000)

        if order_value > max_single_order:
            raise InvalidOrderError(
                f"Order value ₹{order_value} exceeds hard limit ₹{max_single_order}",
                field="order_value",
                value=order_value
            )

        # PAPER MODE CHECK - Orders logged but NOT sent to API
        if self._paper_mode:
            logger.warning(
                "PAPER MODE: Order simulated, NOT sent to Groww API",
                symbol=symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                order_type=order_type,
                price=price
            )

            # Generate mock order ID
            mock_order_id = f"PAPER_{datetime.now().strftime('%Y%m%d%H%M%S')}_{symbol}"

            self.stats['paper_mode_orders'] += 1

            return Order(
                order_id=mock_order_id,
                symbol=symbol,
                exchange=exchange,
                quantity=quantity,
                price=price,
                trigger_price=trigger_price,
                transaction_type=transaction_type,
                order_type=order_type,
                product=product,
                status="PENDING",
                filled_quantity=0,
                timestamp=datetime.now(),
                message="PAPER MODE - Order simulated"
            )

        # Apply rate limiting for real orders
        await self.rate_limiter.acquire('orders')

        # Place order with retry logic
        try:
            logger.info(
                "Placing order",
                symbol=symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                order_type=order_type,
                price=price
            )

            # Call Groww API
            response = await self._call_with_retry(
                self._api.place_order,
                symbol=symbol,
                exchange=exchange,
                transaction_type=transaction_type,
                quantity=quantity,
                order_type=order_type,
                price=price,
                trigger_price=trigger_price,
                product=product,
                segment=segment
            )

            # Parse response
            order = self._parse_order_response(response)

            self.stats['orders_placed'] += 1

            logger.info(
                "Order placed successfully",
                order_id=order.order_id,
                symbol=symbol,
                status=order.status
            )

            return order

        except Exception as e:
            self.stats['api_errors'] += 1
            logger.error(f"Order placement failed: {e}", symbol=symbol)
            raise self._handle_order_error(e, symbol)

    async def cancel_order(
        self,
        order_id: str,
        segment: str = "CASH"
    ) -> bool:
        """
        Cancel pending order.

        Args:
            order_id: Groww order ID
            segment: Market segment

        Returns:
            True if cancellation successful

        Raises:
            OrderError: If cancellation fails
        """
        self._ensure_initialized()

        # Paper mode check
        if self._paper_mode:
            logger.warning(
                "PAPER MODE: Order cancellation simulated",
                order_id=order_id
            )
            return True

        await self.rate_limiter.acquire('orders')

        try:
            logger.info("Cancelling order", order_id=order_id)

            response = await self._call_with_retry(
                self._api.cancel_order,
                order_id=order_id,
                segment=segment
            )

            self.stats['orders_cancelled'] += 1

            logger.info("Order cancelled successfully", order_id=order_id)

            return True

        except Exception as e:
            self.stats['api_errors'] += 1
            logger.error(f"Order cancellation failed: {e}", order_id=order_id)
            raise OrderError(f"Failed to cancel order: {str(e)}", order_id=order_id)

    async def get_order_status(self, order_id: str) -> OrderStatusResponse:
        """
        Get order status.

        Args:
            order_id: Groww order ID

        Returns:
            OrderStatusResponse with order details

        Raises:
            OrderError: If status fetch fails
        """
        self._ensure_initialized()

        # Paper mode - return mock status
        if self._paper_mode and order_id.startswith('PAPER_'):
            logger.debug("PAPER MODE: Returning mock order status", order_id=order_id)
            return OrderStatusResponse(
                order_id=order_id,
                status="PENDING",
                symbol="UNKNOWN",
                quantity=0,
                filled_quantity=0,
                transaction_type="BUY",
                order_type="LIMIT",
                message="Paper mode order"
            )

        await self.rate_limiter.acquire('non_trading')

        try:
            response = await self._call_with_retry(
                self._api.get_order_status,
                order_id=order_id
            )

            return self._parse_order_status_response(response)

        except Exception as e:
            self.stats['api_errors'] += 1
            logger.error(f"Failed to get order status: {e}", order_id=order_id)
            raise OrderError(f"Failed to get order status: {str(e)}", order_id=order_id)

    # ==================== MARKET DATA ====================

    async def get_quote(self, symbol: str, exchange: str = "NSE") -> Quote:
        """
        Get real-time quote.

        Args:
            symbol: Trading symbol
            exchange: Exchange (NSE/BSE)

        Returns:
            Quote object with market data

        Raises:
            DataFetchError: If quote fetch fails
        """
        self._ensure_initialized()

        await self.rate_limiter.acquire('live_data')

        try:
            logger.debug("Fetching quote", symbol=symbol, exchange=exchange)

            response = await self._call_with_retry(
                self._api.get_quote,
                symbol=symbol,
                exchange=exchange
            )

            self.stats['quotes_fetched'] += 1

            return self._parse_quote_response(response, symbol, exchange)

        except Exception as e:
            self.stats['api_errors'] += 1
            logger.error(f"Failed to get quote: {e}", symbol=symbol)
            raise DataFetchError(f"Failed to fetch quote: {str(e)}", data_type="quote")

    async def get_ltp(self, symbol: str, exchange: str = "NSE") -> float:
        """
        Get last traded price.

        Args:
            symbol: Trading symbol
            exchange: Exchange

        Returns:
            Last traded price

        Raises:
            DataFetchError: If LTP fetch fails
        """
        self._ensure_initialized()

        await self.rate_limiter.acquire('live_data')

        try:
            logger.debug("Fetching LTP", symbol=symbol, exchange=exchange)

            response = await self._call_with_retry(
                self._api.get_ltp,
                symbol=symbol,
                exchange=exchange
            )

            ltp = float(response.get('ltp', 0))

            if ltp <= 0:
                raise DataFetchError(f"Invalid LTP value: {ltp}", data_type="ltp")

            return ltp

        except Exception as e:
            self.stats['api_errors'] += 1
            logger.error(f"Failed to get LTP: {e}", symbol=symbol)
            raise DataFetchError(f"Failed to fetch LTP: {str(e)}", data_type="ltp")

    async def get_ohlc(self, symbol: str, exchange: str = "NSE") -> OHLC:
        """
        Get OHLC data.

        Args:
            symbol: Trading symbol
            exchange: Exchange

        Returns:
            OHLC object

        Raises:
            DataFetchError: If OHLC fetch fails
        """
        self._ensure_initialized()

        await self.rate_limiter.acquire('live_data')

        try:
            logger.debug("Fetching OHLC", symbol=symbol, exchange=exchange)

            response = await self._call_with_retry(
                self._api.get_ohlc,
                symbol=symbol,
                exchange=exchange
            )

            return self._parse_ohlc_response(response, symbol, exchange)

        except Exception as e:
            self.stats['api_errors'] += 1
            logger.error(f"Failed to get OHLC: {e}", symbol=symbol)
            raise DataFetchError(f"Failed to fetch OHLC: {str(e)}", data_type="ohlc")

    async def get_historical_data(
        self,
        symbol: str,
        exchange: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1D"
    ) -> HistoricalData:
        """
        Get historical OHLCV data.

        Args:
            symbol: Trading symbol
            exchange: Exchange
            from_date: Start date
            to_date: End date
            interval: Data interval (1D, 1H, 15m, etc.)

        Returns:
            HistoricalData object with candles

        Raises:
            DataFetchError: If historical data fetch fails
        """
        self._ensure_initialized()

        await self.rate_limiter.acquire('non_trading')

        try:
            logger.debug(
                "Fetching historical data",
                symbol=symbol,
                from_date=from_date.date(),
                to_date=to_date.date(),
                interval=interval
            )

            response = await self._call_with_retry(
                self._api.get_historical_data,
                symbol=symbol,
                exchange=exchange,
                from_date=from_date.strftime('%Y-%m-%d'),
                to_date=to_date.strftime('%Y-%m-%d'),
                interval=interval
            )

            return self._parse_historical_data(response, symbol, exchange, interval, from_date, to_date)

        except Exception as e:
            self.stats['api_errors'] += 1
            logger.error(f"Failed to get historical data: {e}", symbol=symbol)
            raise DataFetchError(f"Failed to fetch historical data: {str(e)}", data_type="historical")

    # ==================== PORTFOLIO ====================

    async def get_positions(self) -> List[Position]:
        """
        Get current positions.

        Returns:
            List of Position objects

        Raises:
            DataFetchError: If positions fetch fails
        """
        self._ensure_initialized()

        # Paper mode - return empty positions
        if self._paper_mode:
            logger.debug("PAPER MODE: Returning empty positions")
            return []

        await self.rate_limiter.acquire('non_trading')

        try:
            logger.debug("Fetching positions")

            response = await self._call_with_retry(self._api.get_positions)

            return self._parse_positions_response(response)

        except Exception as e:
            self.stats['api_errors'] += 1
            logger.error(f"Failed to get positions: {e}")
            raise DataFetchError(f"Failed to fetch positions: {str(e)}", data_type="positions")

    async def get_holdings(self) -> List[Holding]:
        """
        Get portfolio holdings.

        Returns:
            List of Holding objects

        Raises:
            DataFetchError: If holdings fetch fails
        """
        self._ensure_initialized()

        # Paper mode - return empty holdings
        if self._paper_mode:
            logger.debug("PAPER MODE: Returning empty holdings")
            return []

        await self.rate_limiter.acquire('non_trading')

        try:
            logger.debug("Fetching holdings")

            response = await self._call_with_retry(self._api.get_holdings)

            return self._parse_holdings_response(response)

        except Exception as e:
            self.stats['api_errors'] += 1
            logger.error(f"Failed to get holdings: {e}")
            raise DataFetchError(f"Failed to fetch holdings: {str(e)}", data_type="holdings")

    # ==================== HELPER METHODS ====================

    def _validate_order_params(
        self,
        symbol: str,
        quantity: int,
        order_type: str,
        price: Optional[float],
        trigger_price: Optional[float],
        product: str,
        segment: str
    ) -> None:
        """Validate order parameters."""
        if not symbol or not symbol.strip():
            raise InvalidOrderError("Symbol cannot be empty", field="symbol")

        if quantity <= 0:
            raise InvalidOrderError(
                f"Quantity must be positive, got {quantity}",
                field="quantity",
                value=quantity
            )

        # Check forbidden products
        forbidden_products = self.config.hard_limits.get('FORBIDDEN_PRODUCTS', [])
        if product in forbidden_products:
            raise InvalidOrderError(
                f"Product {product} is forbidden by hard limits",
                field="product",
                value=product
            )

        # Check forbidden segments
        forbidden_segments = self.config.hard_limits.get('FORBIDDEN_SEGMENTS', [])
        if segment in forbidden_segments:
            raise InvalidOrderError(
                f"Segment {segment} is forbidden by hard limits",
                field="segment",
                value=segment
            )

        # Validate price for LIMIT orders
        if order_type == "LIMIT" and (not price or price <= 0):
            raise InvalidOrderError(
                "LIMIT orders require valid price",
                field="price",
                value=price
            )

        # Validate trigger price for SL orders
        if order_type in ["STOP_LOSS", "STOP_LOSS_MARKET"]:
            if not trigger_price or trigger_price <= 0:
                raise InvalidOrderError(
                    "Stop loss orders require valid trigger price",
                    field="trigger_price",
                    value=trigger_price
                )

    async def _call_with_retry(
        self,
        func,
        max_retries: int = 3,
        backoff_factor: float = 1.5,
        **kwargs
    ) -> Any:
        """
        Call API function with exponential backoff retry.

        Args:
            func: Function to call
            max_retries: Maximum retry attempts
            backoff_factor: Backoff multiplier
            **kwargs: Arguments for function

        Returns:
            Function result

        Raises:
            Exception: If all retries fail
        """
        last_exception = None

        for attempt in range(max_retries):
            try:
                # Call function
                result = func(**kwargs)

                # Handle both sync and async functions
                if asyncio.iscoroutine(result):
                    result = await result

                return result

            except Exception as e:
                last_exception = e

                # Don't retry certain errors
                if isinstance(e, (InvalidOrderError, AuthenticationError)):
                    raise

                if attempt < max_retries - 1:
                    wait_time = backoff_factor ** attempt
                    logger.warning(
                        f"API call failed, retrying in {wait_time}s",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        error=str(e)
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        "API call failed after all retries",
                        attempts=max_retries,
                        error=str(e)
                    )

        raise last_exception

    def _handle_order_error(self, error: Exception, symbol: str) -> OrderError:
        """Convert generic exception to specific OrderError."""
        error_str = str(error).lower()

        if 'insufficient' in error_str or 'balance' in error_str:
            return InsufficientFundsError(f"Insufficient funds for order: {symbol}")

        if 'market closed' in error_str or 'trading closed' in error_str:
            return MarketClosedError(f"Market is closed for {symbol}")

        if 'symbol' in error_str or 'not found' in error_str:
            return SymbolNotFoundError(symbol)

        if 'rate limit' in error_str:
            return RateLimitExceeded(f"Rate limit exceeded for order placement")

        return OrderError(f"Order placement failed: {str(error)}", symbol=symbol)

    # ==================== RESPONSE PARSERS ====================

    def _parse_order_response(self, response: Dict[str, Any]) -> Order:
        """Parse order placement response."""
        return Order(
            order_id=response.get('order_id', ''),
            symbol=response.get('symbol', ''),
            exchange=response.get('exchange', ''),
            quantity=response.get('quantity', 0),
            price=response.get('price'),
            trigger_price=response.get('trigger_price'),
            transaction_type=response.get('transaction_type', ''),
            order_type=response.get('order_type', ''),
            product=response.get('product'),
            status=response.get('status', 'PENDING'),
            filled_quantity=response.get('filled_quantity', 0),
            average_price=response.get('average_price'),
            message=response.get('message')
        )

    def _parse_order_status_response(self, response: Dict[str, Any]) -> OrderStatusResponse:
        """Parse order status response."""
        return OrderStatusResponse(
            order_id=response.get('order_id', ''),
            status=response.get('status', ''),
            symbol=response.get('symbol', ''),
            quantity=response.get('quantity', 0),
            filled_quantity=response.get('filled_quantity', 0),
            average_price=response.get('average_price'),
            pending_quantity=response.get('pending_quantity'),
            price=response.get('price'),
            trigger_price=response.get('trigger_price'),
            transaction_type=response.get('transaction_type', ''),
            order_type=response.get('order_type', ''),
            validity=response.get('validity'),
            product=response.get('product'),
            exchange=response.get('exchange'),
            message=response.get('message')
        )

    def _parse_quote_response(self, response: Dict[str, Any], symbol: str, exchange: str) -> Quote:
        """Parse quote response."""
        return Quote(
            symbol=symbol,
            exchange=exchange,
            ltp=float(response.get('ltp', 0)),
            open=response.get('open'),
            high=response.get('high'),
            low=response.get('low'),
            close=response.get('close'),
            volume=response.get('volume'),
            bid=response.get('bid'),
            ask=response.get('ask'),
            bid_quantity=response.get('bid_quantity'),
            ask_quantity=response.get('ask_quantity'),
            change=response.get('change'),
            change_percent=response.get('change_percent')
        )

    def _parse_ohlc_response(self, response: Dict[str, Any], symbol: str, exchange: str) -> OHLC:
        """Parse OHLC response."""
        return OHLC(
            symbol=symbol,
            exchange=exchange,
            open=float(response.get('open', 0)),
            high=float(response.get('high', 0)),
            low=float(response.get('low', 0)),
            close=float(response.get('close', 0)),
            volume=response.get('volume')
        )

    def _parse_historical_data(
        self,
        response: Dict[str, Any],
        symbol: str,
        exchange: str,
        interval: str,
        from_date: datetime,
        to_date: datetime
    ) -> HistoricalData:
        """Parse historical data response."""
        candles = []

        for candle_data in response.get('candles', []):
            candle = Candle(
                timestamp=datetime.fromisoformat(candle_data.get('timestamp')),
                open=float(candle_data.get('open', 0)),
                high=float(candle_data.get('high', 0)),
                low=float(candle_data.get('low', 0)),
                close=float(candle_data.get('close', 0)),
                volume=int(candle_data.get('volume', 0))
            )
            candles.append(candle)

        return HistoricalData(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            from_date=from_date,
            to_date=to_date,
            candles=candles
        )

    def _parse_positions_response(self, response: Dict[str, Any]) -> List[Position]:
        """Parse positions response."""
        positions = []

        for pos_data in response.get('positions', []):
            position = Position(
                symbol=pos_data.get('symbol', ''),
                exchange=pos_data.get('exchange', ''),
                product=pos_data.get('product', ''),
                quantity=pos_data.get('quantity', 0),
                average_price=float(pos_data.get('average_price', 0)),
                ltp=pos_data.get('ltp'),
                pnl=pos_data.get('pnl'),
                pnl_percent=pos_data.get('pnl_percent'),
                day_change=pos_data.get('day_change'),
                day_change_percent=pos_data.get('day_change_percent')
            )
            positions.append(position)

        return positions

    def _parse_holdings_response(self, response: Dict[str, Any]) -> List[Holding]:
        """Parse holdings response."""
        holdings = []

        for holding_data in response.get('holdings', []):
            holding = Holding(
                symbol=holding_data.get('symbol', ''),
                exchange=holding_data.get('exchange', ''),
                quantity=holding_data.get('quantity', 0),
                average_price=float(holding_data.get('average_price', 0)),
                ltp=holding_data.get('ltp'),
                current_value=holding_data.get('current_value'),
                investment_value=holding_data.get('investment_value'),
                pnl=holding_data.get('pnl'),
                pnl_percent=holding_data.get('pnl_percent'),
                day_change=holding_data.get('day_change'),
                day_change_percent=holding_data.get('day_change_percent')
            )
            holdings.append(holding)

        return holdings

    # ==================== STATUS & INFO ====================

    def is_paper_mode(self) -> bool:
        """Check if running in paper mode."""
        return self._paper_mode

    def get_stats(self) -> Dict[str, Any]:
        """
        Get client statistics.

        Returns:
            Dictionary with statistics
        """
        return {
            'paper_mode': self._paper_mode,
            'initialized': self._initialized,
            'orders_placed': self.stats['orders_placed'],
            'orders_cancelled': self.stats['orders_cancelled'],
            'quotes_fetched': self.stats['quotes_fetched'],
            'api_errors': self.stats['api_errors'],
            'paper_mode_orders': self.stats['paper_mode_orders'],
            'rate_limiter': self.rate_limiter.get_stats(),
            'token_info': self.auth_manager.get_token_info()
        }

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"GrowwClient(paper_mode={self._paper_mode}, "
            f"initialized={self._initialized})"
        )
