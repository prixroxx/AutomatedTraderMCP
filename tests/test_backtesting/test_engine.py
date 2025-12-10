"""
Tests for Backtesting Engine.
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta

from src.trader.backtesting.engine import BacktestEngine, OrderSide
from src.trader.strategies.momentum import MomentumStrategy
from src.trader.strategies.mean_reversion import MeanReversionStrategy


@pytest.fixture
def sample_data():
    """Create sample OHLC data for testing."""
    dates = pd.date_range(start='2024-01-01', periods=100, freq='D')
    data = pd.DataFrame({
        'timestamp': dates,
        'open': [100 + i * 0.5 for i in range(100)],
        'high': [102 + i * 0.5 for i in range(100)],
        'low': [98 + i * 0.5 for i in range(100)],
        'close': [100 + i * 0.5 for i in range(100)],
        'volume': [1000000] * 100
    })
    return data


@pytest.fixture
def engine():
    """Create a backtesting engine."""
    return BacktestEngine(
        initial_capital=100000,
        commission=0.0003,
        slippage=0.0001
    )


def test_engine_initialization(engine):
    """Test engine initializes correctly."""
    assert engine.initial_capital == 100000
    assert engine.cash == 100000
    assert len(engine.positions) == 0
    assert len(engine.orders) == 0
    assert len(engine.trades) == 0


def test_buy_order(engine):
    """Test buy order execution."""
    timestamp = datetime.now()
    success = engine.buy(
        symbol="TESTSTOCK",
        quantity=10,
        price=100.0,
        timestamp=timestamp
    )

    assert success is True
    assert engine.positions["TESTSTOCK"] == 10
    assert engine.cash < 100000  # Cash reduced
    assert len(engine.orders) == 1
    assert len(engine.trades) == 1


def test_buy_insufficient_cash(engine):
    """Test buy order with insufficient cash."""
    timestamp = datetime.now()
    success = engine.buy(
        symbol="TESTSTOCK",
        quantity=10000,  # Too many shares
        price=100.0,
        timestamp=timestamp
    )

    assert success is False
    assert "TESTSTOCK" not in engine.positions
    assert engine.cash == 100000  # Cash unchanged


def test_sell_order(engine):
    """Test sell order execution."""
    timestamp = datetime.now()

    # First buy
    engine.buy("TESTSTOCK", 10, 100.0, timestamp)

    # Then sell
    success = engine.sell("TESTSTOCK", 10, 110.0, timestamp)

    assert success is True
    assert engine.positions["TESTSTOCK"] == 0
    assert engine.cash > engine.initial_capital  # Made profit


def test_sell_insufficient_shares(engine):
    """Test sell order with insufficient shares."""
    timestamp = datetime.now()

    success = engine.sell("TESTSTOCK", 10, 100.0, timestamp)

    assert success is False
    assert len(engine.orders) == 0


def test_momentum_strategy(engine, sample_data):
    """Test momentum strategy on sample data."""
    strategy = MomentumStrategy(fast_period=5, slow_period=10, position_size=1)

    metrics = engine.run_backtest(
        strategy=strategy,
        data=sample_data,
        symbol="TESTSTOCK"
    )

    assert metrics is not None
    assert metrics.total_trades >= 0
    assert metrics.initial_capital == 100000
    assert metrics.win_rate >= 0 and metrics.win_rate <= 100


def test_mean_reversion_strategy(engine, sample_data):
    """Test mean reversion strategy on sample data."""
    # Create data with some volatility
    volatile_data = sample_data.copy()
    for i in range(len(volatile_data)):
        if i % 10 < 5:
            volatile_data.loc[i, 'close'] = 100 + (i % 10) * 2
        else:
            volatile_data.loc[i, 'close'] = 100 - (i % 10) * 2

    strategy = MeanReversionStrategy(period=20, num_std=2.0, position_size=1)

    metrics = engine.run_backtest(
        strategy=strategy,
        data=volatile_data,
        symbol="TESTSTOCK"
    )

    assert metrics is not None
    assert metrics.total_trades >= 0


def test_commission_and_slippage(engine):
    """Test that commission and slippage are applied."""
    timestamp = datetime.now()

    # Buy order
    engine.buy("TESTSTOCK", 10, 100.0, timestamp)

    # Calculate expected cost with slippage and commission
    execution_price = 100.0 * (1 + engine.slippage)
    cost = 10 * execution_price
    commission_cost = cost * engine.commission
    expected_total = cost + commission_cost

    assert engine.cash == pytest.approx(100000 - expected_total, rel=1e-6)


def test_equity_curve(engine, sample_data):
    """Test equity curve generation."""
    strategy = MomentumStrategy(fast_period=5, slow_period=10)

    engine.run_backtest(
        strategy=strategy,
        data=sample_data,
        symbol="TESTSTOCK"
    )

    equity_df = engine.get_equity_curve_df()

    assert len(equity_df) > 0
    assert 'timestamp' in equity_df.columns
    assert 'portfolio_value' in equity_df.columns
    assert 'cash' in equity_df.columns


def test_trades_dataframe(engine, sample_data):
    """Test trades DataFrame generation."""
    strategy = MomentumStrategy(fast_period=5, slow_period=10)

    engine.run_backtest(
        strategy=strategy,
        data=sample_data,
        symbol="TESTSTOCK"
    )

    trades_df = engine.get_trades_df()

    assert 'entry_time' in trades_df.columns
    assert 'exit_time' in trades_df.columns
    assert 'pnl' in trades_df.columns


def test_max_drawdown_calculation(engine, sample_data):
    """Test max drawdown calculation."""
    # Create declining price data
    declining_data = sample_data.copy()
    for i in range(len(declining_data)):
        if i < 50:
            declining_data.loc[i, 'close'] = 150 - i
        else:
            declining_data.loc[i, 'close'] = 100 + (i - 50) * 0.5

    strategy = MomentumStrategy(fast_period=5, slow_period=10)

    metrics = engine.run_backtest(
        strategy=strategy,
        data=declining_data,
        symbol="TESTSTOCK"
    )

    # Max drawdown should be positive
    assert metrics.max_drawdown >= 0


def test_metrics_calculation(engine, sample_data):
    """Test all metrics are calculated correctly."""
    strategy = MomentumStrategy(fast_period=5, slow_period=10)

    metrics = engine.run_backtest(
        strategy=strategy,
        data=sample_data,
        symbol="TESTSTOCK"
    )

    # Check all metrics exist
    assert hasattr(metrics, 'total_trades')
    assert hasattr(metrics, 'winning_trades')
    assert hasattr(metrics, 'losing_trades')
    assert hasattr(metrics, 'win_rate')
    assert hasattr(metrics, 'total_pnl')
    assert hasattr(metrics, 'total_return_percentage')
    assert hasattr(metrics, 'max_drawdown')
    assert hasattr(metrics, 'sharpe_ratio')
    assert hasattr(metrics, 'profit_factor')

    # Win rate should be between 0 and 100
    assert 0 <= metrics.win_rate <= 100

    # Winning + losing trades should equal total trades
    assert metrics.winning_trades + metrics.losing_trades == metrics.total_trades
