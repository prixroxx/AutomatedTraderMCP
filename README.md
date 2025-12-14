# Automated Trading System - MCP Edition

An intelligent, multi-agent swing trading system for Indian equities (NSE/BSE) using Groww API, orchestrated through Model Context Protocol (MCP).

## ⚠️ CRITICAL SAFETY NOTICE

**This system involves REAL MONEY trading. Please read and understand the following:**

- **Paper trading mode is ENFORCED by default** (`FORCE_PAPER_MODE=1`)
- **Minimum 2 weeks of paper trading required** before considering live trading
- **Hard-coded safety limits** cannot be overridden (see `config/trading_limits.yaml`)
- **Kill switch** automatically halts trading on dangerous conditions
- **Conservative default limits**: ₹50k portfolio, ₹5k max position
- **Never compromise safety for speed**

## Tech Stack

- **Python 3.9+**: Core language
- **Groww API**: Indian equities trading
- **MCP (Model Context Protocol)**: LLM orchestration
- **FastMCP**: MCP server framework
- **Pydantic**: Data validation
- **Structlog**: Structured logging
- **SQLite**: GTT order storage
- **Pandas/Numpy**: Data processing
- **Click**: CLI framework
- **pytest**: Testing

## Architecture

```
┌──────────────────────────────────────────────────┐
│                   LLM (Claude)                   │
│           Orchestrates Trading Decisions         │
└─────────────────┬────────────────────────────────┘
                  │ MCP Protocol
┌─────────────────▼────────────────────────────────┐
│                 MCP Server                       │
│  Tools: get_quote, place_order, create_gtt,     │
│         get_positions, get_news, backtest        │
└─────┬─────────┬─────────┬──────────┬────────────┘
      │         │         │          │
┌─────▼───┐ ┌──▼──┐ ┌────▼────┐ ┌──▼─────┐
│ Groww   │ │ Risk│ │   GTT   │ │ News   │
│   API   │ │ Mgr │ │ Monitor │ │Fetcher │
└─────────┘ └─────┘ └─────────┘ └────────┘
```

## Quick Start

### 1. Prerequisites

```bash
# Python 3.9 or higher
python --version

# Git (for version control)
git --version
```

### 2. Clone and Setup

```bash
# Navigate to project directory
cd C:\Users\prixr\UpGrad\AutomatedTrader\AutomatedTraderMCP

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate

# Unix/MacOS:
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install development dependencies (for testing)
pip install -r requirements-dev.txt
```

### 3. Configure Environment

```bash
# Copy environment template
copy .env.example .env

# Edit .env and add your Groww API credentials
# GROWW_API_KEY=your_api_key
# GROWW_SECRET=your_secret
# FORCE_PAPER_MODE=1  # KEEP THIS AS 1 FOR SAFETY
```

### 4. Verify Configuration

```python
# Test configuration loading
python -c "from src.trader.core.config import get_config; print(get_config().to_dict())"
```

## Configuration

### Default Configuration (`config/default_config.yaml`)

```yaml
trading:
  mode: "paper"  # Always starts in paper mode
  default_exchange: "NSE"

risk:
  max_portfolio_value: 50000     # ₹50k
  max_position_size: 5000        # ₹5k per position
  max_daily_loss: 2000           # ₹2k daily loss limit
  max_open_positions: 3          # Max 3 positions

api:
  rate_limits:
    orders_per_second: 10
    live_data_per_second: 8
    non_trading_per_second: 15
```

### Hard Limits (`config/trading_limits.yaml`)

**THESE CANNOT BE OVERRIDDEN:**

```yaml
ABSOLUTE_LIMITS:
  MAX_SINGLE_ORDER_VALUE: 10000      # ₹10k
  MAX_DAILY_ORDERS: 15
  MAX_PORTFOLIO_VALUE: 50000         # ₹50k
  MAX_DAILY_LOSS_HARD: 5000          # ₹5k (kill switch)
  FORBIDDEN_SEGMENTS: ["FNO"]        # No derivatives
  FORBIDDEN_PRODUCTS: ["MIS"]        # No margin trading
```

## Project Structure

```
AutomatedTraderMCP/
├── config/                        # Configuration files
│   ├── default_config.yaml        # Default settings
│   ├── trading_limits.yaml        # Hard-coded safety limits
│   └── config.local.yaml.example  # Local override template
│
├── src/trader/                    # Main source code
│   ├── api/                       # Groww API integration
│   │   ├── auth.py               # Authentication manager 
│   │   ├── client.py             # API client 
│   │   ├── exceptions.py         # Custom exceptions 
│   │   ├── models.py             # Data models 
│   │   └── rate_limiter.py       # Rate limiting 
│   │
│   ├── core/                      # Core utilities
│   │   ├── config.py             # Configuration manager 
│   │   └── logging_config.py     # Logging setup 
│   │
│   ├── risk/                      # Risk management 
│   ├── gtt/                       # GTT system 
│   ├── mcp/                       # MCP server 
│   ├── backtesting/               # Backtesting engine 
│   ├── data/                      # Data management 
│   └── cli/                       # CLI commands 
│
├── tests/                         # Test suite 
├── data/                          # Runtime data (gitignored)
│   ├── logs/                      # Log files
│   ├── cache/                     # Cached data
│   └── gtt_orders.db             # GTT database
│
├── docs/                          # Documentation (TODO)
├── requirements.txt               # Python dependencies 
├── pyproject.toml                # Project configuration 
├── .env.example                  # Environment template 
└── README.md                     # This file 
```

## Safety Features

### 1. Multi-Layer Order Validation

Every order goes through 7 validation layers:
1. Kill Switch Check
2. Hard Limit Validation
3. Config Limit Validation
4. Daily Limit Checks
5. Risk Manager Approval
6. Paper Mode Check
7. API Call (only if all pass)

### 2. Kill Switch

Automatically halts trading on:
- Daily loss > ₹5k
- 5+ consecutive losses
- API error rate > 30%
- Network failure > 60 seconds
- Manual trigger

**Recovery requires:**
- Manual restart
- 60-minute cooldown
- Admin approval code

### 3. Paper Trading Mode

- **FORCE_PAPER_MODE=1** (default)
- All orders logged but NOT sent to API
- Returns mock order IDs
- Full system functionality for testing

### 4. Comprehensive Logging

- Every API call logged
- Every order attempt logged
- JSON format for parsing
- Daily log rotation
- 90-day retention

## Usage

### CLI Commands

```bash
# Check system status
trader status

# Check risk metrics
trader risk-status

# Run backtest
trader backtest --strategy momentum --symbol RELIANCE --start 2024-01-01

# List GTT orders
trader gtt list

# Activate kill switch (emergency)
trader kill-switch --activate --reason manual
```

### MCP Tools (via Claude)

The MCP server provides 32 tools organized into 4 categories:

#### 📊 Market Data Tools (7 tools)

```python
# Get real-time quote with bid/ask/volume
get_quote(symbol="RELIANCE", exchange="NSE")

# Get last traded price
get_ltp(symbol="TCS", exchange="NSE")

# Get OHLC data for current day
get_ohlc(symbol="INFY", exchange="NSE")

# Get historical candles (customizable interval)
get_historical_data(symbol="RELIANCE", exchange="NSE", days_back=90, interval="1d")

# Get multiple LTPs at once
get_multiple_ltps(symbols=["RELIANCE", "TCS", "INFY"], exchange="NSE")

# Check market status (open/closed)
get_market_status()
```

#### 📝 Order Management Tools (8 tools)

```python
# Place order with full validation (7-layer risk checks)
place_order(
    symbol="RELIANCE",
    transaction_type="BUY",
    quantity=1,
    order_type="LIMIT",
    price=2500.00,
    exchange="NSE"
)

# Cancel pending order
cancel_order(order_id="123456789", segment="EQUITY")

# Get order status
get_order_status(order_id="123456789")

# Get comprehensive risk metrics
get_risk_status()

# Get today's order summary
get_order_book()

# Emergency: Activate kill switch
activate_kill_switch(reason="manual", message="Market volatility too high")

# Resume trading after cooldown
deactivate_kill_switch(admin_approval="your_admin_code")
```

#### 💼 Portfolio Management Tools (7 tools)

```python
# Get current open positions
get_positions()

# Get long-term holdings
get_holdings()

# Get comprehensive portfolio analytics
get_portfolio_summary()

# Get specific position
get_position_by_symbol(symbol="RELIANCE", exchange="NSE")

# Get specific holding
get_holding_by_symbol(symbol="TCS", exchange="NSE")

# Calculate diversification breakdown
calculate_portfolio_allocation()
```

#### ⏰ GTT (Good Till Triggered) Tools (10 tools)

```python
# Create GTT order
create_gtt(
    symbol="RELIANCE",
    trigger_price=2400.00,
    action="BUY",
    quantity=1,
    order_type="LIMIT",
    limit_price=2400.00,
    exchange="NSE"
)

# List GTT orders (with optional filtering)
list_gtts(status="ACTIVE")
list_gtts(symbol="RELIANCE")
list_gtts()  # All GTTs

# Get specific GTT details
get_gtt(gtt_id=123)

# Cancel GTT order
cancel_gtt(gtt_id=123)

# Get GTT system statistics
get_gtt_statistics()

# Check if trigger condition is met (without executing)
check_gtt_trigger_condition(gtt_id=123)

# Manually trigger GTT (bypass price check)
trigger_gtt_manually(gtt_id=123)

# Pause/resume GTT monitoring
pause_gtt_monitoring()
resume_gtt_monitoring()
```

## Contributing

This is a personal trading system. If you're adapting this code:

1. **Test extensively in paper mode** (minimum 2 weeks)
2. **Start with minimal capital** (₹10-20k)
3. **Monitor continuously**
4. **Document all changes**
5. **Never disable safety features**

## Resources

- **Groww API Docs**: [Groww API Docs](https://groww.in/trade-api/docs/python-sdk)
- **MCP Protocol**: [MCP Protocol](https://modelcontextprotocol.io)
- **MCP Server**: [MCP Server Docs](https://github.com/modelcontextprotocol/servers)

## Disclaimer

**USE AT YOUR OWN RISK**

This software is provided "as is" without warranty of any kind. Trading involves substantial risk of loss. The authors and contributors are not responsible for any financial losses incurred through the use of this system.

- Not financial advice
- No guarantees of profitability
- Test thoroughly before live use
- Start with minimal capital
- Monitor continuously

---

**Components**: Configuration, API Client, Risk Management, GTT System, MCP Server (32 tools), Backtesting, News, CLI, Tests

**Safety**: Paper Mode Enforced 🛡️

**Production Ready**: Yes - Ready for paper trading and testing
