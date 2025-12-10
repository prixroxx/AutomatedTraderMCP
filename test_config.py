#!/usr/bin/env python
"""Quick configuration test script."""

from src.trader.core.config import get_config

def main():
    c = get_config()

    print("=" * 50)
    print("CONFIGURATION VERIFIED [OK]")
    print("=" * 50)
    print()

    print("Trading Settings:")
    print(f"  Mode: {c.get('trading.mode')}")
    print(f"  Paper mode enforced: {c.is_paper_mode()}")
    print(f"  Default exchange: {c.get('trading.default_exchange')}")
    print()

    print("Risk Limits (Configurable):")
    print(f"  Max portfolio: Rs {c.get('risk.max_portfolio_value'):,}")
    print(f"  Max position: Rs {c.get('risk.max_position_size'):,}")
    print(f"  Max daily loss: Rs {c.get('risk.max_daily_loss'):,}")
    print(f"  Max open positions: {c.get('risk.max_open_positions')}")
    print()

    print("Hard Limits (NON-OVERRIDABLE):")
    print(f"  Max single order: Rs {c.hard_limits.MAX_SINGLE_ORDER_VALUE:,}")
    print(f"  Max daily orders: {c.hard_limits.MAX_DAILY_ORDERS}")
    print(f"  Max portfolio (hard): Rs {c.hard_limits.MAX_PORTFOLIO_VALUE:,}")
    print(f"  Kill switch at loss: Rs {c.hard_limits.MAX_DAILY_LOSS_HARD:,}")
    print(f"  Forbidden segments: {c.hard_limits.FORBIDDEN_SEGMENTS}")
    print(f"  Forbidden products: {c.hard_limits.FORBIDDEN_PRODUCTS}")
    print()

    print("API Rate Limits (Conservative):")
    print(f"  Orders/sec: {c.get('api.rate_limits.orders_per_second')} (API allows 15)")
    print(f"  Live data/sec: {c.get('api.rate_limits.live_data_per_second')} (API allows 10)")
    print(f"  Non-trading/sec: {c.get('api.rate_limits.non_trading_per_second')} (API allows 20)")
    print()

    print("GTT Configuration:")
    print(f"  Monitor interval: {c.get('gtt.monitor_interval_seconds')} seconds")
    print(f"  Max active GTTs: {c.get('gtt.max_active_gtt')}")
    print()

    print("Kill Switch Conditions:")
    for i, cond in enumerate(c.kill_switch_conditions, 1):
        print(f"  {i}. {cond.description}")
    print()

    print("=" * 50)
    print("[OK] All configuration loaded successfully!")
    print("=" * 50)

if __name__ == "__main__":
    main()
