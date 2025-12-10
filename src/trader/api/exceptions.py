"""
Custom exceptions for Groww API interactions.

This module defines all custom exceptions used throughout the trading system,
providing clear error categorization and helpful error messages.
"""


class GrowwAPIError(Exception):
    """Base exception for all Groww API related errors."""

    def __init__(self, message: str, error_code: str = None, response_data: dict = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.response_data = response_data or {}

    def __str__(self):
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message


class AuthenticationError(GrowwAPIError):
    """Authentication failed - invalid API key, secret, or token."""
    pass


class RateLimitExceeded(GrowwAPIError):
    """API rate limit exceeded."""

    def __init__(self, message: str, retry_after: int = None):
        super().__init__(message)
        self.retry_after = retry_after  # Seconds to wait before retry

    def __str__(self):
        if self.retry_after:
            return f"{self.message} (retry after {self.retry_after}s)"
        return self.message


class OrderError(GrowwAPIError):
    """Order placement, modification, or cancellation failed."""

    def __init__(
        self,
        message: str,
        order_id: str = None,
        symbol: str = None,
        error_code: str = None
    ):
        super().__init__(message, error_code)
        self.order_id = order_id
        self.symbol = symbol


class InsufficientFundsError(OrderError):
    """Insufficient funds to place order."""
    pass


class InvalidOrderError(OrderError):
    """Order parameters are invalid."""

    def __init__(self, message: str, field: str = None, value: any = None):
        super().__init__(message)
        self.field = field  # Which field caused the error
        self.value = value  # Invalid value


class MarketClosedError(OrderError):
    """Attempted to place order when market is closed."""
    pass


class SymbolNotFoundError(GrowwAPIError):
    """Stock symbol not found or invalid."""

    def __init__(self, symbol: str, exchange: str = None):
        message = f"Symbol '{symbol}' not found"
        if exchange:
            message += f" on {exchange}"
        super().__init__(message)
        self.symbol = symbol
        self.exchange = exchange


class DataFetchError(GrowwAPIError):
    """Failed to fetch market data."""

    def __init__(self, message: str, data_type: str = None):
        super().__init__(message)
        self.data_type = data_type  # Type of data that failed (quote, ohlc, historical)


class NetworkError(GrowwAPIError):
    """Network connectivity issue."""

    def __init__(self, message: str, original_exception: Exception = None):
        super().__init__(message)
        self.original_exception = original_exception


class TimeoutError(NetworkError):
    """API request timed out."""
    pass


class ValidationError(Exception):
    """Validation error for internal data validation."""

    def __init__(self, message: str, field: str = None, value: any = None):
        super().__init__(message)
        self.field = field
        self.value = value


class ConfigurationError(Exception):
    """Configuration error - invalid settings or missing required config."""
    pass


class RiskManagementError(Exception):
    """Risk management constraint violation."""

    def __init__(
        self,
        message: str,
        limit_type: str = None,
        current_value: float = None,
        limit_value: float = None
    ):
        super().__init__(message)
        self.limit_type = limit_type  # Type of limit exceeded
        self.current_value = current_value
        self.limit_value = limit_value


class KillSwitchActive(RiskManagementError):
    """Kill switch is active - trading is halted."""

    def __init__(self, reason: str, activated_at: str = None):
        message = f"Kill switch active: {reason}"
        super().__init__(message)
        self.reason = reason
        self.activated_at = activated_at


class PositionLimitExceeded(RiskManagementError):
    """Position count or size limit exceeded."""
    pass


class DailyLossLimitExceeded(RiskManagementError):
    """Daily loss limit exceeded."""
    pass


class GTTError(GrowwAPIError):
    """GTT (Good Till Triggered) order error."""

    def __init__(self, message: str, gtt_id: int = None):
        super().__init__(message)
        self.gtt_id = gtt_id


class GTTNotFoundError(GTTError):
    """GTT order not found."""
    pass


class GTTExecutionError(GTTError):
    """GTT order execution failed."""
    pass


class BacktestError(Exception):
    """Backtesting engine error."""

    def __init__(self, message: str, strategy_name: str = None):
        super().__init__(message)
        self.strategy_name = strategy_name


class DataNotFoundError(Exception):
    """Required data not found (e.g., historical data missing)."""

    def __init__(self, message: str, data_type: str = None, symbol: str = None):
        super().__init__(message)
        self.data_type = data_type
        self.symbol = symbol
