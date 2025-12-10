"""
Mean Reversion Trading Strategy.

Buys when price is significantly below average and sells when it returns to average.
Uses Bollinger Bands to identify overbought/oversold conditions.
"""

from typing import Deque
from collections import deque
import statistics

from .base import BaseStrategy
from ..api.models import OHLC


class MeanReversionStrategy(BaseStrategy):
    """
    Mean Reversion Strategy using Bollinger Bands.

    Strategy Logic:
    - BUY: When price touches lower Bollinger Band (oversold)
    - SELL: When price reaches middle band or upper band (profit target)
    """

    def __init__(
        self,
        period: int = 20,
        num_std: float = 2.0,
        position_size: int = 1
    ):
        """
        Initialize Mean Reversion Strategy.

        Args:
            period: Period for moving average and std dev (default: 20)
            num_std: Number of standard deviations for bands (default: 2.0)
            position_size: Number of shares to trade (default: 1)
        """
        super().__init__(name=f"MeanReversion({period},{num_std})")

        self.period = period
        self.num_std = num_std
        self.position_size = position_size

        # Price history for calculating bands
        self.prices: Deque[float] = deque(maxlen=period)

        # Entry price for profit target
        self.entry_price = None

    def on_data(self, data: OHLC) -> None:
        """
        Process new market data and execute mean reversion strategy.

        Args:
            data: New OHLC data point
        """
        # Add new price to history
        self.prices.append(data.close)

        # Need enough data for Bollinger Bands
        if len(self.prices) < self.period:
            return

        # Calculate Bollinger Bands
        middle_band = statistics.mean(self.prices)
        std_dev = statistics.stdev(self.prices)
        upper_band = middle_band + (self.num_std * std_dev)
        lower_band = middle_band - (self.num_std * std_dev)

        current_position = self.get_position(data.symbol)
        current_price = data.close

        # No position: Look for buy signal (price at lower band)
        if current_position == 0:
            if current_price <= lower_band:
                self.log(
                    "Price at lower band - BUY signal (oversold)",
                    price=current_price,
                    lower_band=lower_band,
                    middle_band=middle_band
                )
                success = self.engine.buy(
                    symbol=data.symbol,
                    quantity=self.position_size,
                    price=current_price,
                    timestamp=data.timestamp
                )
                if success:
                    self.entry_price = current_price

        # Have position: Look for sell signal (price at middle or upper band)
        else:
            # Sell at middle band (profit target)
            if current_price >= middle_band:
                self.log(
                    "Price returned to middle band - SELL signal",
                    price=current_price,
                    entry_price=self.entry_price,
                    middle_band=middle_band,
                    pnl_pct=((current_price - self.entry_price) / self.entry_price * 100)
                    if self.entry_price else 0
                )
                self.engine.sell(
                    symbol=data.symbol,
                    quantity=current_position,
                    price=current_price,
                    timestamp=data.timestamp
                )
                self.entry_price = None

            # Also sell if price reaches upper band (unexpected strong move)
            elif current_price >= upper_band:
                self.log(
                    "Price at upper band - SELL signal (take profit)",
                    price=current_price,
                    entry_price=self.entry_price,
                    upper_band=upper_band,
                    pnl_pct=((current_price - self.entry_price) / self.entry_price * 100)
                    if self.entry_price else 0
                )
                self.engine.sell(
                    symbol=data.symbol,
                    quantity=current_position,
                    price=current_price,
                    timestamp=data.timestamp
                )
                self.entry_price = None
