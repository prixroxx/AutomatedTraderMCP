"""
Backtesting Engine for Strategy Testing.

This module provides a backtesting framework to test trading strategies
against historical data before deploying them live.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
import pandas as pd

from ..api.models import OHLC
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class OrderSide(Enum):
    """Order side enumeration."""
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class BacktestOrder:
    """Represents an order in backtesting."""
    timestamp: datetime
    symbol: str
    side: OrderSide
    quantity: int
    price: float
    order_type: str = "MARKET"


@dataclass
class BacktestTrade:
    """Represents an executed trade in backtesting."""
    entry_time: datetime
    exit_time: Optional[datetime]
    symbol: str
    side: OrderSide
    quantity: int
    entry_price: float
    exit_price: Optional[float]
    pnl: Optional[float] = None
    pnl_percentage: Optional[float] = None
    status: str = "OPEN"  # OPEN, CLOSED


@dataclass
class BacktestMetrics:
    """Performance metrics from backtesting."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    total_return_percentage: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    max_drawdown: float
    sharpe_ratio: float
    profit_factor: float
    initial_capital: float
    final_capital: float


class BacktestEngine:
    """
    Backtesting engine for testing trading strategies.

    Simulates strategy execution on historical data and calculates
    performance metrics.
    """

    def __init__(
        self,
        initial_capital: float = 100000,
        commission: float = 0.0003,  # 0.03% per trade
        slippage: float = 0.0001  # 0.01% slippage
    ):
        """
        Initialize backtesting engine.

        Args:
            initial_capital: Starting capital for backtesting
            commission: Commission rate per trade (default: 0.03%)
            slippage: Slippage rate per trade (default: 0.01%)
        """
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage

        self.cash = initial_capital
        self.positions: Dict[str, int] = {}  # symbol -> quantity
        self.orders: List[BacktestOrder] = []
        self.trades: List[BacktestTrade] = []
        self.equity_curve: List[Dict[str, Any]] = []

        logger.info(
            "Backtest engine initialized",
            initial_capital=initial_capital,
            commission=commission,
            slippage=slippage
        )

    def run_backtest(
        self,
        strategy: 'BaseStrategy',
        data: pd.DataFrame,
        symbol: str
    ) -> BacktestMetrics:
        """
        Run backtest for a strategy on historical data.

        Args:
            strategy: Strategy instance to test
            data: DataFrame with OHLC data (columns: timestamp, open, high, low, close, volume)
            symbol: Stock symbol being tested

        Returns:
            BacktestMetrics with performance results
        """
        logger.info(
            f"Starting backtest for {symbol}",
            strategy=strategy.__class__.__name__,
            data_points=len(data),
            start_date=data.iloc[0]['timestamp'] if len(data) > 0 else None,
            end_date=data.iloc[-1]['timestamp'] if len(data) > 0 else None
        )

        # Reset state
        self._reset()

        # Initialize strategy
        strategy.initialize(self)

        # Iterate through historical data
        for idx, row in data.iterrows():
            timestamp = row['timestamp']
            ohlc = OHLC(
                symbol=symbol,
                exchange="NSE",
                timestamp=timestamp,
                open=row['open'],
                high=row['high'],
                low=row['low'],
                close=row['close'],
                volume=row['volume']
            )

            # Update strategy with new data
            strategy.on_data(ohlc)

            # Update equity curve
            self._update_equity_curve(timestamp, ohlc.close)

        # Close any remaining open positions
        self._close_all_positions(data.iloc[-1]['timestamp'], data.iloc[-1]['close'])

        # Calculate metrics
        metrics = self._calculate_metrics()

        logger.info(
            "Backtest completed",
            total_trades=metrics.total_trades,
            win_rate=metrics.win_rate,
            total_return=metrics.total_return_percentage
        )

        return metrics

    def buy(
        self,
        symbol: str,
        quantity: int,
        price: float,
        timestamp: datetime
    ) -> bool:
        """
        Execute a buy order in backtesting.

        Args:
            symbol: Stock symbol
            quantity: Number of shares
            price: Price per share
            timestamp: Order timestamp

        Returns:
            True if order executed successfully
        """
        # Apply slippage
        execution_price = price * (1 + self.slippage)

        # Calculate total cost including commission
        cost = quantity * execution_price
        commission_cost = cost * self.commission
        total_cost = cost + commission_cost

        # Check if we have enough cash
        if total_cost > self.cash:
            logger.warning(
                "Insufficient cash for buy order",
                required=total_cost,
                available=self.cash
            )
            return False

        # Execute order
        self.cash -= total_cost
        self.positions[symbol] = self.positions.get(symbol, 0) + quantity

        # Record order
        order = BacktestOrder(
            timestamp=timestamp,
            symbol=symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            price=execution_price
        )
        self.orders.append(order)

        # Record trade (entry)
        trade = BacktestTrade(
            entry_time=timestamp,
            exit_time=None,
            symbol=symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            entry_price=execution_price,
            exit_price=None
        )
        self.trades.append(trade)

        logger.debug(
            "Buy order executed",
            symbol=symbol,
            quantity=quantity,
            price=execution_price,
            cost=total_cost
        )

        return True

    def sell(
        self,
        symbol: str,
        quantity: int,
        price: float,
        timestamp: datetime
    ) -> bool:
        """
        Execute a sell order in backtesting.

        Args:
            symbol: Stock symbol
            quantity: Number of shares
            price: Price per share
            timestamp: Order timestamp

        Returns:
            True if order executed successfully
        """
        # Check if we have enough shares
        current_position = self.positions.get(symbol, 0)
        if current_position < quantity:
            logger.warning(
                "Insufficient shares for sell order",
                required=quantity,
                available=current_position
            )
            return False

        # Apply slippage (negative for sell)
        execution_price = price * (1 - self.slippage)

        # Calculate proceeds minus commission
        proceeds = quantity * execution_price
        commission_cost = proceeds * self.commission
        net_proceeds = proceeds - commission_cost

        # Execute order
        self.cash += net_proceeds
        self.positions[symbol] -= quantity

        # Record order
        order = BacktestOrder(
            timestamp=timestamp,
            symbol=symbol,
            side=OrderSide.SELL,
            quantity=quantity,
            price=execution_price
        )
        self.orders.append(order)

        # Find matching buy trade and close it
        for trade in reversed(self.trades):
            if trade.symbol == symbol and trade.status == "OPEN" and trade.side == OrderSide.BUY:
                trade.exit_time = timestamp
                trade.exit_price = execution_price
                trade.pnl = (execution_price - trade.entry_price) * trade.quantity
                trade.pnl_percentage = (
                    (execution_price - trade.entry_price) / trade.entry_price * 100
                )
                trade.status = "CLOSED"
                break

        logger.debug(
            "Sell order executed",
            symbol=symbol,
            quantity=quantity,
            price=execution_price,
            proceeds=net_proceeds
        )

        return True

    def get_position(self, symbol: str) -> int:
        """Get current position size for a symbol."""
        return self.positions.get(symbol, 0)

    def get_portfolio_value(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total portfolio value.

        Args:
            current_prices: Dict mapping symbols to current prices

        Returns:
            Total portfolio value (cash + positions)
        """
        positions_value = sum(
            qty * current_prices.get(symbol, 0)
            for symbol, qty in self.positions.items()
        )
        return self.cash + positions_value

    def _reset(self) -> None:
        """Reset engine state for new backtest."""
        self.cash = self.initial_capital
        self.positions = {}
        self.orders = []
        self.trades = []
        self.equity_curve = []

    def _update_equity_curve(self, timestamp: datetime, current_price: float) -> None:
        """Update equity curve with current portfolio value."""
        portfolio_value = self.get_portfolio_value(
            {symbol: current_price for symbol in self.positions.keys()}
        )

        self.equity_curve.append({
            'timestamp': timestamp,
            'portfolio_value': portfolio_value,
            'cash': self.cash,
            'positions_value': portfolio_value - self.cash
        })

    def _close_all_positions(self, timestamp: datetime, price: float) -> None:
        """Close all open positions at end of backtest."""
        for symbol, quantity in list(self.positions.items()):
            if quantity > 0:
                self.sell(symbol, quantity, price, timestamp)

    def _calculate_metrics(self) -> BacktestMetrics:
        """Calculate performance metrics from backtest results."""
        closed_trades = [t for t in self.trades if t.status == "CLOSED"]

        if not closed_trades:
            logger.warning("No closed trades in backtest")
            return BacktestMetrics(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                total_pnl=0.0,
                total_return_percentage=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                largest_win=0.0,
                largest_loss=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                profit_factor=0.0,
                initial_capital=self.initial_capital,
                final_capital=self.cash
            )

        # Basic metrics
        total_trades = len(closed_trades)
        winning_trades = [t for t in closed_trades if t.pnl > 0]
        losing_trades = [t for t in closed_trades if t.pnl <= 0]

        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0

        # P&L metrics
        total_pnl = sum(t.pnl for t in closed_trades)
        total_return_pct = (total_pnl / self.initial_capital * 100)

        avg_win = sum(t.pnl for t in winning_trades) / win_count if win_count > 0 else 0
        avg_loss = sum(t.pnl for t in losing_trades) / loss_count if loss_count > 0 else 0

        largest_win = max((t.pnl for t in winning_trades), default=0)
        largest_loss = min((t.pnl for t in losing_trades), default=0)

        # Profit factor
        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0

        # Max drawdown
        max_drawdown = self._calculate_max_drawdown()

        # Sharpe ratio (simplified)
        returns = [t.pnl_percentage for t in closed_trades]
        sharpe_ratio = self._calculate_sharpe_ratio(returns)

        return BacktestMetrics(
            total_trades=total_trades,
            winning_trades=win_count,
            losing_trades=loss_count,
            win_rate=win_rate,
            total_pnl=total_pnl,
            total_return_percentage=total_return_pct,
            avg_win=avg_win,
            avg_loss=avg_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            profit_factor=profit_factor,
            initial_capital=self.initial_capital,
            final_capital=self.cash
        )

    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown from equity curve."""
        if not self.equity_curve:
            return 0.0

        equity_values = [point['portfolio_value'] for point in self.equity_curve]
        peak = equity_values[0]
        max_dd = 0.0

        for value in equity_values:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak * 100
            max_dd = max(max_dd, drawdown)

        return max_dd

    def _calculate_sharpe_ratio(self, returns: List[float]) -> float:
        """
        Calculate Sharpe ratio (simplified).

        Args:
            returns: List of return percentages

        Returns:
            Sharpe ratio
        """
        if not returns:
            return 0.0

        import statistics

        mean_return = statistics.mean(returns)
        std_return = statistics.stdev(returns) if len(returns) > 1 else 0

        if std_return == 0:
            return 0.0

        # Simplified Sharpe (assuming 0% risk-free rate)
        sharpe = mean_return / std_return

        return sharpe

    def get_equity_curve_df(self) -> pd.DataFrame:
        """Get equity curve as pandas DataFrame."""
        return pd.DataFrame(self.equity_curve)

    def get_trades_df(self) -> pd.DataFrame:
        """Get all trades as pandas DataFrame."""
        trades_data = []
        for trade in self.trades:
            trades_data.append({
                'entry_time': trade.entry_time,
                'exit_time': trade.exit_time,
                'symbol': trade.symbol,
                'side': trade.side.value,
                'quantity': trade.quantity,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'pnl': trade.pnl,
                'pnl_percentage': trade.pnl_percentage,
                'status': trade.status
            })
        return pd.DataFrame(trades_data)
