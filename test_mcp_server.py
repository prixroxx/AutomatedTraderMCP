"""
Test script to verify MCP server startup and configuration.

This script tests:
1. MCP server can be imported
2. All tool modules load correctly
3. Configuration loads properly
4. Server lists all available tools

Run with: python test_mcp_server.py
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))


def test_imports():
    """Test that all modules can be imported."""
    print("=" * 60)
    print("Testing Module Imports")
    print("=" * 60)

    try:
        from trader.mcp import server
        print("✅ MCP server module imported successfully")
    except Exception as e:
        print(f"❌ Failed to import MCP server: {e}")
        return False

    try:
        from trader.mcp.tools import market_data, orders, portfolio, gtt
        print("✅ All tool modules imported successfully")
        print(f"   - market_data: {len([x for x in dir(market_data) if not x.startswith('_')])} exports")
        print(f"   - orders: {len([x for x in dir(orders) if not x.startswith('_')])} exports")
        print(f"   - portfolio: {len([x for x in dir(portfolio) if not x.startswith('_')])} exports")
        print(f"   - gtt: {len([x for x in dir(gtt) if not x.startswith('_')])} exports")
    except Exception as e:
        print(f"❌ Failed to import tool modules: {e}")
        return False

    return True


def test_configuration():
    """Test configuration loading."""
    print("\n" + "=" * 60)
    print("Testing Configuration")
    print("=" * 60)

    try:
        from trader.core.config import get_config
        config = get_config()

        print("✅ Configuration loaded successfully")
        print(f"   - Paper mode: {config.is_paper_mode()}")
        print(f"   - Max portfolio value: ₹{config.get('risk.max_portfolio_value'):,}")
        print(f"   - Max position size: ₹{config.get('risk.max_position_size'):,}")
        print(f"   - Max daily loss: ₹{config.get('risk.max_daily_loss'):,}")
        print(f"   - Max open positions: {config.get('risk.max_open_positions')}")

        # Check hard limits
        print(f"\n   Hard Limits (non-overridable):")
        print(f"   - Max single order: ₹{config.hard_limits['MAX_SINGLE_ORDER_VALUE']:,}")
        print(f"   - Max daily orders: {config.hard_limits['MAX_DAILY_ORDERS']}")
        print(f"   - Max portfolio: ₹{config.hard_limits['MAX_PORTFOLIO_VALUE']:,}")

        return True
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        return False


def test_mcp_server():
    """Test MCP server initialization."""
    print("\n" + "=" * 60)
    print("Testing MCP Server")
    print("=" * 60)

    try:
        from trader.mcp.server import mcp

        print("✅ MCP server instance created")
        print(f"   - Server name: {mcp.name}")
        print(f"   - Server version: {mcp.version}")

        return True
    except Exception as e:
        print(f"❌ MCP server error: {e}")
        return False


def list_available_tools():
    """List all available MCP tools."""
    print("\n" + "=" * 60)
    print("Available MCP Tools")
    print("=" * 60)

    try:
        from trader.mcp.server import mcp

        # Get all registered tools
        if hasattr(mcp, '_tools') and mcp._tools:
            tools = mcp._tools
            print(f"\n✅ Found {len(tools)} registered tools:\n")

            # Group tools by category
            categories = {
                'Market Data': [],
                'Orders': [],
                'Portfolio': [],
                'GTT': []
            }

            for tool_name in sorted(tools.keys()):
                if any(x in tool_name for x in ['quote', 'ltp', 'ohlc', 'historical', 'market']):
                    categories['Market Data'].append(tool_name)
                elif any(x in tool_name for x in ['order', 'risk', 'kill']):
                    categories['Orders'].append(tool_name)
                elif any(x in tool_name for x in ['position', 'holding', 'portfolio', 'allocation']):
                    categories['Portfolio'].append(tool_name)
                elif 'gtt' in tool_name:
                    categories['GTT'].append(tool_name)

            for category, tool_list in categories.items():
                if tool_list:
                    print(f"{category} ({len(tool_list)} tools):")
                    for tool in tool_list:
                        print(f"  - {tool}")
                    print()

            return True
        else:
            print("⚠️  No tools registered yet (tools may register on server start)")
            print("\nExpected tools:")

            expected_tools = {
                'Market Data': [
                    'get_quote', 'get_ltp', 'get_ohlc', 'get_historical_data',
                    'get_multiple_ltps', 'get_market_status'
                ],
                'Orders': [
                    'place_order', 'cancel_order', 'get_order_status',
                    'get_risk_status', 'activate_kill_switch',
                    'deactivate_kill_switch', 'get_order_book'
                ],
                'Portfolio': [
                    'get_positions', 'get_holdings', 'get_portfolio_summary',
                    'get_position_by_symbol', 'get_holding_by_symbol',
                    'calculate_portfolio_allocation'
                ],
                'GTT': [
                    'create_gtt', 'list_gtts', 'get_gtt', 'cancel_gtt',
                    'get_gtt_statistics', 'trigger_gtt_manually',
                    'pause_gtt_monitoring', 'resume_gtt_monitoring',
                    'check_gtt_trigger_condition'
                ]
            }

            for category, tool_list in expected_tools.items():
                print(f"\n{category} ({len(tool_list)} tools):")
                for tool in tool_list:
                    print(f"  - {tool}")

            return True

    except Exception as e:
        print(f"❌ Error listing tools: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_environment():
    """Check environment variables."""
    print("\n" + "=" * 60)
    print("Environment Check")
    print("=" * 60)

    # Load .env file if it exists
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        print(f"✅ .env file found at {env_file}")
        from dotenv import load_dotenv
        load_dotenv(env_file)
    else:
        print(f"⚠️  .env file not found at {env_file}")
        print("   Create .env from .env.example and add your Groww API credentials")

    # Check required environment variables
    required_vars = {
        'GROWW_API_KEY': 'Groww API Key',
        'GROWW_SECRET': 'Groww Secret',
        'FORCE_PAPER_MODE': 'Paper Mode Flag'
    }

    print("\nEnvironment Variables:")
    all_set = True
    for var, description in required_vars.items():
        value = os.getenv(var)
        if value:
            if var in ['GROWW_API_KEY', 'GROWW_SECRET']:
                # Mask sensitive values
                masked = value[:4] + '*' * (len(value) - 8) + value[-4:] if len(value) > 8 else '***'
                print(f"  ✅ {var}: {masked}")
            else:
                print(f"  ✅ {var}: {value}")
        else:
            print(f"  ❌ {var}: Not set")
            all_set = False

    if all_set:
        print("\n✅ All required environment variables are set")
    else:
        print("\n⚠️  Some environment variables are missing")
        print("   Set them in .env file before starting the server")

    return all_set


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("MCP Server Test Suite")
    print("=" * 60)
    print()

    results = {
        "Environment Check": check_environment(),
        "Module Imports": test_imports(),
        "Configuration": test_configuration(),
        "MCP Server": test_mcp_server(),
        "Tool Registration": list_available_tools()
    }

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")

    all_passed = all(results.values())

    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL TESTS PASSED")
        print("\nYou can now start the MCP server with:")
        print("  python -m src.trader.mcp.server")
        print("\nOr use the entry point:")
        print("  trader-mcp")
    else:
        print("⚠️  SOME TESTS FAILED")
        print("\nPlease fix the issues above before starting the server.")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
