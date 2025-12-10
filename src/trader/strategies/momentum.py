"""
Momentum Trading Strategy.

Buys when price momentum is strong and sells when it weakens.
Uses Simple Moving Average (SMA) crossover as the momentum indicator.
"""

from typing import Deque
from collections import deque

from .base import BaseStrategy
from ..api.models import OHLC


class MomentumStrategy(BaseStrategy):
    """
    Simple Momentum Strategy using SMA crossover.

    Strategy Logic:
    - BUY: When fast SMA crosses above slow SMA (bullish momentum)
    - SELL: When fast SMA crosses below slow SMA (bearish momentum)
    """

    def __init__(
        self,
        fast_period: int = 10,
        slow_period: int = 30,
        position_size: int = 1
    ):
        """
        Initialize Momentum Strategy.

        Args:
            fast_period: Period for fast moving average (default: 10)
            slow_period: Period for slow moving average (default: 30)
            position_size: Number of shares to trade (default: 1)
        """
        super().__init__(name=f"Momentum({fast_period},{slow_period})")

        self.fast_period = fast_period
        self.slow_period = slow_period
        self.position_size = position_size

        # Price history for calculating SMAs
        self.prices: Deque[float] = deque(maxlen=slow_period)

        # Track previous SMAs for crossover detection
        self.prev_fast_sma = None
        self.prev_slow_sma = None

    def on_data(self, data: OHLC) -> None:
        """
        Process new market data and execute momentum strategy.

        Args:
            data: New OHLC data point
        """
        # Add new price to history
        self.prices.append(data.close)

        # Need enough data for slow SMA
        if len(self.prices) < self.slow_period:
            return

        # Calculate SMAs
        fast_sma = self._calculate_sma(self.fast_period)
        slow_sma = self._calculate_sma(self.slow_period)

        # Need previous values for crossover detection
        if self.prev_fast_sma is None or self.prev_slow_sma is None:
            self.prev_fast_sma = fast_sma
            self.prev_slow_sma = slow_sma
            return

        # Check for crossovers
        current_position = self.get_position(data.symbol)

        # Bullish crossover: Fast SMA crosses above Slow SMA
        if (
            self.prev_fast_sma <= self.prev_slow_sma
            and fast_sma > slow_sma
            and current_position == 0
        ):
            self.log(
                "Bullish crossover detected - BUY signal",
                fast_sma=fast_sma,
                slow_sma=slow_sma,
                price=data.close
            )
            self.engine.buy(
                symbol=data.symbol,
                quantity=self.position_size,
                price=data.close,
                timestamp=data.timestamp
            )

        # Bearish crossover: Fast SMA crosses below Slow SMA
        elif (
            self.prev_fast_sma >= self.prev_slow_sma
            and fast_sma < slow_sma
            and current_position > 0
        ):
            self.log(
                "Bearish crossover detected - SELL signal",
                fast_sma=fast_sma,
                slow_sma=slow_sma,
                price=data.close
            )
            self.engine.sell(
                symbol=data.symbol,
                quantity=current_position,
                price=data.close,
                timestamp=data.timestamp
            )

        # Update previous SMAs
        self.prev_fast_sma = fast_sma
        self.prev_slow_sma = slow_sma

    def _calculate_sma(self, period: int) -> float:
        """
        Calculate Simple Moving Average.

        Args:
            period: Number of periods for SMA

        Returns:
            SMA value
        """
        if len(self.prices) < period:
            return sum(self.prices) / len(self.prices)

        recent_prices = list(self.prices)[-period:]
        return sum(recent_prices) / period
