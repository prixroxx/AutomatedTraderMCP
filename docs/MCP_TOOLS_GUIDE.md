# MCP Tools Guide - Claude Usage Examples

This guide demonstrates how Claude can interact with the Automated Trading System through the Model Context Protocol (MCP).

## Table of Contents

- [Getting Started](#getting-started)
- [Market Data Tools](#market-data-tools)
- [Order Management Tools](#order-management-tools)
- [Portfolio Management Tools](#portfolio-management-tools)
- [GTT Tools](#gtt-tools)
- [Common Workflows](#common-workflows)
- [Safety Guidelines](#safety-guidelines)

---

## Getting Started

### Prerequisites

1. **MCP Server Running**: Start the server with `python -m src.trader.mcp.server` or `trader-mcp`
2. **Paper Mode Enabled**: `FORCE_PAPER_MODE=1` in `.env` (default)
3. **Credentials Set**: Groww API credentials in `.env`

### Connecting Claude

When the MCP server is running, Claude can access all 32 trading tools through the MCP protocol.

---

## Market Data Tools

### Get Real-Time Quote

```python
# Get comprehensive quote data
get_quote(symbol="RELIANCE", exchange="NSE")
```

**Returns:**
```json
{
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "ltp": 2450.50,
  "open": 2440.00,
  "high": 2460.00,
  "low": 2435.00,
  "close": 2445.00,
  "volume": 1250000,
  "bid": 2450.00,
  "ask": 2451.00,
  "timestamp": "2024-01-15T14:30:00"
}
```

### Get Last Traded Price (LTP)

```python
# Quick price check
get_ltp(symbol="TCS", exchange="NSE")
```

**Returns:**
```json
{
  "symbol": "TCS",
  "exchange": "NSE",
  "ltp": 3650.75,
  "timestamp": "2024-01-15T14:30:15"
}
```

### Get Multiple Stock Prices

```python
# Get prices for multiple stocks at once
get_multiple_ltps(
    symbols=["RELIANCE", "TCS", "INFY", "HDFC"],
    exchange="NSE"
)
```

**Returns:**
```json
{
  "RELIANCE": 2450.50,
  "TCS": 3650.75,
  "INFY": 1420.30,
  "HDFC": 1650.00
}
```

### Get Historical Data

```python
# Get 90 days of daily candles
get_historical_data(
    symbol="RELIANCE",
    exchange="NSE",
    days_back=90,
    interval="1d"
)
```

**Supported intervals**: `"1m"`, `"5m"`, `"15m"`, `"1h"`, `"1d"`, `"1w"`

### Check Market Status

```python
# Check if market is open
get_market_status()
```

**Returns:**
```json
{
  "is_market_open": true,
  "market_type": "regular",
  "current_time": "2024-01-15T14:30:00",
  "trading_hours": {
    "pre_market": "09:00 - 09:15 IST",
    "regular_market": "09:15 - 15:30 IST",
    "post_market": "15:30 - 16:00 IST"
  }
}
```

---

## Order Management Tools

### Place an Order

```python
# Place a LIMIT buy order
place_order(
    symbol="RELIANCE",
    transaction_type="BUY",
    quantity=1,
    order_type="LIMIT",
    price=2400.00,
    exchange="NSE",
    product="CNC",  # Delivery
    segment="EQUITY"
)
```

**Order Types:**
- `"LIMIT"` - Limit order (requires `price`)
- `"MARKET"` - Market order (executes at current price)
- `"SL"` - Stop-Loss limit (requires `price` and `trigger_price`)
- `"SL-M"` - Stop-Loss market (requires `trigger_price`)

**Returns:**
```json
{
  "order_id": "20240115123456789",
  "symbol": "RELIANCE",
  "quantity": 1,
  "price": 2400.00,
  "status": "PENDING",
  "paper_mode": true,
  "warning": "PAPER MODE - Order simulated, not sent to exchange"
}
```

### Check Risk Status

```python
# Get comprehensive risk metrics before placing orders
get_risk_status()
```

**Returns:**
```json
{
  "daily_pnl": -150.50,
  "open_positions": 2,
  "daily_order_count": 5,
  "kill_switch_active": false,
  "paper_mode": true,
  "limits": {
    "max_portfolio_value": 50000,
    "max_position_size": 5000,
    "max_daily_loss": 2000,
    "max_open_positions": 3,
    "max_single_order": 10000,
    "max_daily_orders": 15
  },
  "available": {
    "can_place_orders": true,
    "positions_available": 1,
    "orders_remaining_today": 10
  }
}
```

### Cancel an Order

```python
# Cancel a pending order
cancel_order(order_id="20240115123456789", segment="EQUITY")
```

### Emergency: Kill Switch

```python
# EMERGENCY: Halt all trading
activate_kill_switch(
    reason="manual",
    message="Excessive market volatility detected"
)

# After 60-minute cooldown and review:
deactivate_kill_switch(admin_approval="your_admin_code")
```

---

## Portfolio Management Tools

### View Current Positions

```python
# Get all open positions
get_positions()
```

**Returns:**
```json
[
  {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "quantity": 2,
    "average_price": 2430.00,
    "ltp": 2450.50,
    "pnl": 41.00,
    "pnl_percentage": 0.84,
    "product": "CNC"
  }
]
```

### View Holdings

```python
# Get long-term holdings
get_holdings()
```

### Portfolio Summary with Analytics

```python
# Get comprehensive portfolio analysis
get_portfolio_summary()
```

**Returns:**
```json
{
  "overview": {
    "total_portfolio_value": 15250.50,
    "total_pnl": 325.75,
    "total_pnl_percentage": 2.18,
    "positions_count": 2,
    "holdings_count": 1,
    "total_stocks": 3
  },
  "largest_position": {
    "symbol": "RELIANCE",
    "value": 4901.00,
    "pnl": 41.00
  },
  "performance": {
    "best_performer": {
      "symbol": "TCS",
      "pnl": 150.00,
      "pnl_pct": 4.29
    },
    "worst_performer": {
      "symbol": "INFY",
      "pnl": -25.50,
      "pnl_pct": -1.79
    }
  },
  "risk_metrics": {
    "daily_pnl": 125.00,
    "max_portfolio_value": 50000,
    "utilization_percentage": 30.50
  }
}
```

### Check Diversification

```python
# Analyze portfolio allocation
calculate_portfolio_allocation()
```

**Returns:**
```json
{
  "total_value": 15250.50,
  "allocations": [
    {
      "symbol": "RELIANCE",
      "value": 4901.00,
      "percentage": 32.14,
      "type": "position"
    },
    {
      "symbol": "TCS",
      "value": 3650.75,
      "percentage": 23.94,
      "type": "holding"
    }
  ],
  "diversification": {
    "number_of_stocks": 3,
    "largest_allocation": 32.14,
    "top_3_concentration": 80.52
  }
}
```

---

## GTT Tools

### Create a GTT Order

```python
# Create a "buy on dip" order
create_gtt(
    symbol="RELIANCE",
    trigger_price=2400.00,
    action="BUY",
    quantity=1,
    order_type="LIMIT",
    limit_price=2400.00,
    exchange="NSE"
)
```

**GTT Logic:**
- **BUY GTT**: Executes when `LTP <= trigger_price` (buy when price falls)
- **SELL GTT**: Executes when `LTP >= trigger_price` (sell when price rises)

**Returns:**
```json
{
  "gtt_id": 1,
  "symbol": "RELIANCE",
  "trigger_price": 2400.00,
  "action": "BUY",
  "status": "ACTIVE",
  "message": "GTT order created. Will BUY 1 shares of RELIANCE when price falls to ₹2400.0"
}
```

### List GTT Orders

```python
# List all active GTTs
list_gtts(status="ACTIVE")

# List GTTs for specific symbol
list_gtts(symbol="RELIANCE")

# List all GTTs
list_gtts()
```

### Check GTT Trigger Condition

```python
# Check if GTT would trigger at current price (without executing)
check_gtt_trigger_condition(gtt_id=1)
```

**Returns:**
```json
{
  "gtt_id": 1,
  "symbol": "RELIANCE",
  "trigger_price": 2400.00,
  "current_price": 2450.50,
  "should_trigger": false,
  "condition": "LTP (2450.50) <= Trigger (2400.00)",
  "distance_to_trigger": {
    "absolute": 50.50,
    "percentage": 2.10
  },
  "message": "Condition not met - LTP (2450.50) <= Trigger (2400.00)"
}
```

### GTT System Statistics

```python
# Get GTT system overview
get_gtt_statistics()
```

**Returns:**
```json
{
  "monitoring": {
    "is_running": true,
    "check_interval_seconds": 30
  },
  "totals": {
    "total_gtts": 10,
    "active": 3,
    "triggered": 2,
    "completed": 4,
    "cancelled": 1,
    "failed": 0
  },
  "performance": {
    "success_rate": 100.0,
    "completion_rate": 66.67
  }
}
```

### Cancel GTT

```python
# Cancel an active GTT
cancel_gtt(gtt_id=1)
```

---

## Common Workflows

### Workflow 1: Research → Buy Decision

```python
# 1. Check market status
market = get_market_status()

# 2. Get current price
quote = get_quote(symbol="RELIANCE", exchange="NSE")

# 3. Check historical trend
history = get_historical_data(
    symbol="RELIANCE",
    days_back=30,
    interval="1d"
)

# 4. Check risk limits
risk = get_risk_status()

# 5. If all checks pass, place order
if market["is_market_open"] and risk["can_place_orders"]:
    order = place_order(
        symbol="RELIANCE",
        transaction_type="BUY",
        quantity=1,
        order_type="LIMIT",
        price=2400.00
    )
```

### Workflow 2: Set Stop-Loss with GTT

```python
# 1. Check current position
position = get_position_by_symbol(symbol="RELIANCE")

# 2. Calculate stop-loss price (5% below average)
stop_loss_price = position["average_price"] * 0.95

# 3. Create GTT sell order
gtt = create_gtt(
    symbol="RELIANCE",
    trigger_price=stop_loss_price,
    action="SELL",
    quantity=position["quantity"],
    order_type="MARKET"
)
```

### Workflow 3: Portfolio Rebalancing

```python
# 1. Get portfolio allocation
allocation = calculate_portfolio_allocation()

# 2. Identify overweight positions (>30%)
overweight = [
    stock for stock in allocation["allocations"]
    if stock["percentage"] > 30.0
]

# 3. Create GTT sell orders for partial exits
for stock in overweight:
    # Sell 25% when price rises 5%
    current_price = get_ltp(stock["symbol"])
    target_price = current_price * 1.05

    create_gtt(
        symbol=stock["symbol"],
        trigger_price=target_price,
        action="SELL",
        quantity=int(stock["quantity"] * 0.25),
        order_type="LIMIT",
        limit_price=target_price
    )
```

### Workflow 4: Daily Risk Check

```python
# Morning routine before market opens
def daily_risk_check():
    # 1. Check risk status
    risk = get_risk_status()

    # 2. Check portfolio
    portfolio = get_portfolio_summary()

    # 3. Check active GTTs
    gtts = list_gtts(status="ACTIVE")

    # 4. Review yesterday's orders
    orders = get_order_book()

    return {
        "risk_status": risk,
        "portfolio": portfolio,
        "active_gtts": len(gtts),
        "yesterdays_orders": orders["daily_order_count"]
    }
```

---

## Safety Guidelines

### ⚠️ CRITICAL: Always Check Before Trading

1. **Paper Mode Verification**:
   ```python
   risk = get_risk_status()
   if not risk["paper_mode"]:
       print("⚠️ LIVE MODE - Real money at risk!")
   ```

2. **Risk Limits Check**:
   ```python
   risk = get_risk_status()
   if risk["daily_pnl"] < -1500:
       print("⚠️ Approaching daily loss limit")
   ```

3. **Kill Switch Status**:
   ```python
   risk = get_risk_status()
   if risk["kill_switch_active"]:
       print("🚨 KILL SWITCH ACTIVE - Trading halted")
   ```

### Order Validation Pipeline

Every order goes through **7 validation layers**:

1. ✅ Kill Switch Check
2. ✅ Hard Limit Validation (₹10k max per order)
3. ✅ Config Limit Validation (₹5k max position)
4. ✅ Daily Limit Checks (15 orders max per day)
5. ✅ Risk Manager Approval
6. ✅ Paper Mode Check
7. ✅ API Call (only if all pass)

### Position Sizing Rules

```python
# GOOD: Within limits
place_order(
    symbol="RELIANCE",
    quantity=1,  # ₹2,450 < ₹5,000 limit
    price=2450.00
)

# BAD: Exceeds position limit
place_order(
    symbol="RELIANCE",
    quantity=3,  # ₹7,350 > ₹5,000 limit ❌
    price=2450.00
)
# Will be rejected by risk manager
```

### GTT Best Practices

1. **Always check distance to trigger**:
   ```python
   status = check_gtt_trigger_condition(gtt_id=1)
   if status["distance_to_trigger"]["percentage"] < 1.0:
       print("⚠️ GTT close to triggering!")
   ```

2. **Monitor GTT statistics**:
   ```python
   stats = get_gtt_statistics()
   if stats["totals"]["failed"] > 0:
       print("⚠️ Some GTTs failed - review errors")
   ```

3. **Review active GTTs regularly**:
   ```python
   active_gtts = list_gtts(status="ACTIVE")
   print(f"Currently monitoring {len(active_gtts)} GTT orders")
   ```

---

## Error Handling

### Common Errors and Solutions

**Order Rejected - Exceeds Daily Loss Limit**:
```json
{
  "error": "Order rejected: Daily loss limit exceeded (-2150.00 < -2000.00)"
}
```
**Solution**: Stop trading for the day, review strategy.

**Kill Switch Active**:
```json
{
  "error": "Kill switch is ACTIVE - trading halted. Cannot place order."
}
```
**Solution**: Wait for cooldown, review activation reason, deactivate if appropriate.

**Market Closed**:
```python
# Check before placing orders
market = get_market_status()
if not market["is_market_open"]:
    print("Market is closed - use GTT orders instead")
```

---

## Quick Reference

### Market Data
| Tool | Use Case |
|------|----------|
| `get_quote()` | Comprehensive quote data |
| `get_ltp()` | Quick price check |
| `get_ohlc()` | Daily candle data |
| `get_historical_data()` | Trend analysis |
| `get_market_status()` | Trading hours check |

### Orders
| Tool | Use Case |
|------|----------|
| `place_order()` | Place new order |
| `get_risk_status()` | Pre-order validation |
| `cancel_order()` | Cancel pending order |
| `activate_kill_switch()` | Emergency halt |

### Portfolio
| Tool | Use Case |
|------|----------|
| `get_positions()` | Open positions |
| `get_portfolio_summary()` | Complete analysis |
| `calculate_portfolio_allocation()` | Diversification check |

### GTT
| Tool | Use Case |
|------|----------|
| `create_gtt()` | Auto-trigger orders |
| `list_gtts()` | View active GTTs |
| `check_gtt_trigger_condition()` | Pre-check trigger |
| `get_gtt_statistics()` | System health |

---

## Support & Resources

- **Configuration**: `config/default_config.yaml`
- **Hard Limits**: `config/trading_limits.yaml`
- **Logs**: `data/logs/`
- **GTT Database**: `data/gtt_orders.db`

For issues or questions, review the main README.md or check the logs.

---

**Remember**: Always start in **PAPER MODE** (FORCE_PAPER_MODE=1). Minimum 2 weeks of paper trading before considering live mode. 🛡️
