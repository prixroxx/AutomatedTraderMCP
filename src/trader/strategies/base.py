"""
Base Strategy Class for Trading Strategies.

All trading strategies should inherit from BaseStrategy and implement
the required methods.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..api.models import OHLC
from ..core.logging_config import get_logger

if TYPE_CHECKING:
    from ..backtesting.engine import BacktestEngine

logger = get_logger(__name__)


class BaseStrategy(ABC):
    """
    Abstract base class for trading strategies.

    All strategies must implement:
    - initialize(): Setup strategy state
    - on_data(): Process new market data and generate signals
    """

    def __init__(self, name: str = "BaseStrategy"):
        """
        Initialize strategy.

        Args:
            name: Strategy name for logging
        """
        self.name = name
        self.engine: 'BacktestEngine' = None
        self.data_history = []

        logger.info(f"Strategy initialized: {name}")

    def initialize(self, engine: 'BacktestEngine') -> None:
        """
        Initialize strategy with backtesting engine.

        Args:
            engine: BacktestEngine instance
        """
        self.engine = engine
        self.data_history = []
        logger.info(f"{self.name}: Strategy initialized with engine")

    @abstractmethod
    def on_data(self, data: OHLC) -> None:
        """
        Called when new market data arrives.

        Strategies should implement their logic here to:
        1. Analyze the new data
        2. Generate trading signals
        3. Execute orders via self.engine.buy() or self.engine.sell()

        Args:
            data: New OHLC data point
        """
        pass

    def get_position(self, symbol: str) -> int:
        """
        Get current position for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Current position size (0 if no position)
        """
        return self.engine.get_position(symbol) if self.engine else 0

    def has_position(self, symbol: str) -> bool:
        """
        Check if we have an open position in a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            True if position exists
        """
        return self.get_position(symbol) > 0

    def log(self, message: str, **kwargs) -> None:
        """
        Log a message with strategy name prefix.

        Args:
            message: Log message
            **kwargs: Additional log context
        """
        logger.info(f"{self.name}: {message}", **kwargs)
