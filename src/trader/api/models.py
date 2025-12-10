"""
Pydantic models for API data structures.

This module defines type-safe data models for all API interactions,
ensuring data validation and providing clear interfaces.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator
from enum import Enum


# Enums for type safety

class OrderType(str, Enum):
    """Order types supported by Groww."""
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP_LOSS = "STOP_LOSS"
    STOP_LOSS_MARKET = "STOP_LOSS_MARKET"


class TransactionType(str, Enum):
    """Transaction types."""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """Order execution status."""
    PENDING = "PENDING"
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class ProductType(str, Enum):
    """Product types."""
    CNC = "CNC"  # Cash and Carry (delivery)
    MIS = "MIS"  # Margin Intraday Squareoff
    NRML = "NRML"  # Normal (F&O)


class Exchange(str, Enum):
    """Supported exchanges."""
    NSE = "NSE"
    BSE = "BSE"
    MCX = "MCX"


class GTTStatus(str, Enum):
    """GTT order status."""
    ACTIVE = "ACTIVE"
    TRIGGERED = "TRIGGERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


# Data Models

class Order(BaseModel):
    """Order model."""
    order_id: str = Field(..., description="Groww order ID")
    symbol: str = Field(..., description="Trading symbol")
    exchange: Optional[str] = Field(None, description="Exchange (NSE/BSE/MCX)")
    quantity: int = Field(..., gt=0, description="Order quantity")
    price: Optional[float] = Field(None, ge=0, description="Order price")
    trigger_price: Optional[float] = Field(None, ge=0, description="Trigger price for SL orders")
    transaction_type: str = Field(..., description="BUY or SELL")
    order_type: str = Field(..., description="Order type (LIMIT/MARKET/etc)")
    product: Optional[str] = Field(None, description="Product type (CNC/MIS/NRML)")
    status: Optional[str] = Field(None, description="Order status")
    filled_quantity: Optional[int] = Field(0, ge=0, description="Filled quantity")
    average_price: Optional[float] = Field(None, ge=0, description="Average fill price")
    timestamp: datetime = Field(default_factory=datetime.now, description="Order timestamp")
    message: Optional[str] = Field(None, description="Status message")

    class Config:
        use_enum_values = True


class OrderStatusResponse(BaseModel):
    """Order status response model."""
    order_id: str
    status: str
    symbol: str
    quantity: int
    filled_quantity: int = 0
    average_price: Optional[float] = None
    pending_quantity: Optional[int] = None
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    transaction_type: str
    order_type: str
    validity: Optional[str] = None
    product: Optional[str] = None
    exchange: Optional[str] = None
    order_timestamp: Optional[datetime] = None
    exchange_timestamp: Optional[datetime] = None
    message: Optional[str] = None


class Quote(BaseModel):
    """Real-time quote model."""
    symbol: str
    exchange: str
    ltp: float = Field(..., description="Last traded price")
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[int] = Field(None, ge=0)
    bid: Optional[float] = Field(None, ge=0)
    ask: Optional[float] = Field(None, ge=0)
    bid_quantity: Optional[int] = Field(None, ge=0)
    ask_quantity: Optional[int] = Field(None, ge=0)
    change: Optional[float] = None
    change_percent: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class OHLC(BaseModel):
    """OHLC (Open, High, Low, Close) data model."""
    symbol: str
    exchange: str
    open: float = Field(..., ge=0)
    high: float = Field(..., ge=0)
    low: float = Field(..., ge=0)
    close: float = Field(..., ge=0)
    volume: Optional[int] = Field(None, ge=0)
    date: datetime = Field(default_factory=datetime.now)


class Candle(BaseModel):
    """Single candlestick data."""
    timestamp: datetime
    open: float = Field(..., ge=0)
    high: float = Field(..., ge=0)
    low: float = Field(..., ge=0)
    close: float = Field(..., ge=0)
    volume: int = Field(..., ge=0)

    @validator('high')
    def validate_high(cls, v, values):
        """Ensure high is not less than low."""
        if 'low' in values and v < values['low']:
            raise ValueError("High cannot be less than low")
        return v

    @validator('low')
    def validate_low(cls, v, values):
        """Ensure low is not greater than high."""
        if 'high' in values and v > values['high']:
            raise ValueError("Low cannot be greater than high")
        return v


class HistoricalData(BaseModel):
    """Historical OHLCV data model."""
    symbol: str
    exchange: str
    interval: str = Field(..., description="Data interval (1D, 1H, etc.)")
    from_date: datetime
    to_date: datetime
    candles: List[Candle] = Field(default_factory=list)

    def to_dict_list(self) -> List[Dict[str, Any]]:
        """Convert candles to list of dictionaries."""
        return [candle.dict() for candle in self.candles]


class Position(BaseModel):
    """Trading position model."""
    symbol: str
    exchange: str
    product: str
    quantity: int
    average_price: float = Field(..., ge=0)
    ltp: Optional[float] = Field(None, ge=0, description="Last traded price")
    pnl: Optional[float] = None
    pnl_percent: Optional[float] = None
    day_change: Optional[float] = None
    day_change_percent: Optional[float] = None


class Holding(BaseModel):
    """Portfolio holding model."""
    symbol: str
    exchange: str
    quantity: int = Field(..., ge=0)
    average_price: float = Field(..., ge=0)
    ltp: Optional[float] = Field(None, ge=0)
    current_value: Optional[float] = Field(None, ge=0)
    investment_value: Optional[float] = Field(None, ge=0)
    pnl: Optional[float] = None
    pnl_percent: Optional[float] = None
    day_change: Optional[float] = None
    day_change_percent: Optional[float] = None


class AccountSummary(BaseModel):
    """Account summary model."""
    available_cash: float = Field(..., ge=0)
    used_margin: float = Field(default=0, ge=0)
    available_margin: Optional[float] = Field(None, ge=0)
    total_collateral: Optional[float] = Field(None, ge=0)
    portfolio_value: Optional[float] = Field(None, ge=0)
    total_pnl: Optional[float] = None
    day_pnl: Optional[float] = None


class GTTOrder(BaseModel):
    """GTT (Good Till Triggered) order model."""
    id: Optional[int] = Field(None, description="Database ID")
    symbol: str
    exchange: str
    trigger_price: float = Field(..., gt=0)
    order_type: str = Field(..., description="LIMIT or MARKET")
    action: str = Field(..., description="BUY or SELL")
    quantity: int = Field(..., gt=0)
    limit_price: Optional[float] = Field(None, gt=0)
    status: str = Field(default="ACTIVE")
    created_at: datetime = Field(default_factory=datetime.now)
    triggered_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    order_id: Optional[str] = Field(None, description="Groww order ID after execution")
    error_message: Optional[str] = None

    class Config:
        use_enum_values = True


class NewsArticle(BaseModel):
    """News article model."""
    title: str
    summary: Optional[str] = None
    url: str
    source: str
    published_date: datetime
    symbols: Optional[List[str]] = Field(default_factory=list, description="Related stock symbols")
    sentiment: Optional[str] = Field(None, description="positive, negative, neutral")


class RiskMetrics(BaseModel):
    """Risk management metrics."""
    daily_pnl: float
    open_positions: int
    max_positions: int
    used_capital: float
    available_capital: float
    daily_loss_limit: float
    daily_order_count: int
    max_daily_orders: int
    kill_switch_active: bool
    is_healthy: bool
    warnings: List[str] = Field(default_factory=list)


class BacktestResult(BaseModel):
    """Backtest result model."""
    strategy_name: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    max_drawdown_pct: float
    sharpe_ratio: float
    commission_paid: float
