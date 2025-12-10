"""
MCP Tools for Portfolio Management.

Provides tools for viewing positions, holdings, and portfolio analytics.
"""

from typing import Optional, Dict, Any, List

from mcp.server.fastmcp import Context

from ..server import mcp
from ...core.logging_config import get_logger

logger = get_logger(__name__)


@mcp.tool()
async def get_positions(
    ctx: Optional[Context] = None
) -> List[Dict[str, Any]]:
    """
    Get current open positions (intraday + delivery).

    Returns all positions with:
    - Symbol and exchange
    - Quantity (positive for long, negative for short)
    - Average price
    - Current price (LTP)
    - P&L (realized and unrealized)
    - Product type (CNC/INTRADAY)

    Returns:
        List of all open positions

    Example:
        get_positions()
    """
    logger.info("Fetching current positions")

    try:
        groww_client = ctx.request_context.groww_client

        positions = await groww_client.get_positions()

        logger.info(f"Positions fetched: {len(positions)} open positions")

        return [position.model_dump() for position in positions]

    except Exception as e:
        logger.error(f"Error fetching positions: {e}")
        raise


@mcp.tool()
async def get_holdings(
    ctx: Optional[Context] = None
) -> List[Dict[str, Any]]:
    """
    Get portfolio holdings (delivery stocks held long-term).

    Returns all holdings with:
    - Symbol and exchange
    - Quantity
    - Average buy price
    - Current price (LTP)
    - Total P&L
    - Current value

    Returns:
        List of all holdings

    Example:
        get_holdings()
    """
    logger.info("Fetching portfolio holdings")

    try:
        groww_client = ctx.request_context.groww_client

        holdings = await groww_client.get_holdings()

        logger.info(f"Holdings fetched: {len(holdings)} stocks")

        return [holding.model_dump() for holding in holdings]

    except Exception as e:
        logger.error(f"Error fetching holdings: {e}")
        raise


@mcp.tool()
async def get_portfolio_summary(
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Get comprehensive portfolio summary with analytics.

    Returns:
        Portfolio summary including:
        - Total portfolio value
        - Total P&L (realized + unrealized)
        - Number of positions/holdings
        - Largest position
        - Best/worst performers
        - Sector allocation (if available)

    Example:
        get_portfolio_summary()
    """
    logger.info("Generating portfolio summary")

    try:
        groww_client = ctx.request_context.groww_client
        risk_manager = ctx.request_context.risk_manager
        config = ctx.request_context.config

        # Get positions and holdings
        positions = await groww_client.get_positions()
        holdings = await groww_client.get_holdings()

        # Calculate metrics
        total_positions = len(positions)
        total_holdings = len(holdings)

        # Calculate total values
        positions_value = sum(pos.quantity * pos.ltp for pos in positions)
        holdings_value = sum(
            holding.quantity * holding.ltp for holding in holdings
        )
        total_value = positions_value + holdings_value

        # Calculate P&L
        positions_pnl = sum(pos.pnl for pos in positions)
        holdings_pnl = sum(holding.pnl for holding in holdings)
        total_pnl = positions_pnl + holdings_pnl

        # Find largest position
        all_items = positions + holdings
        largest = None
        if all_items:
            largest = max(
                all_items,
                key=lambda x: abs(x.quantity * x.ltp)
            )

        # Find best and worst performers (by percentage)
        best_performer = None
        worst_performer = None

        if all_items:
            items_with_pnl_pct = [
                {
                    "symbol": item.symbol,
                    "pnl": item.pnl,
                    "pnl_pct": (item.pnl / (item.quantity * item.average_price) * 100)
                    if item.quantity * item.average_price != 0
                    else 0
                }
                for item in all_items
            ]

            best_performer = max(items_with_pnl_pct, key=lambda x: x["pnl_pct"])
            worst_performer = min(items_with_pnl_pct, key=lambda x: x["pnl_pct"])

        # Get risk status
        risk_status = await risk_manager.get_status()

        summary = {
            "overview": {
                "total_portfolio_value": total_value,
                "total_pnl": total_pnl,
                "total_pnl_percentage": (total_pnl / total_value * 100) if total_value > 0 else 0,
                "positions_count": total_positions,
                "holdings_count": total_holdings,
                "total_stocks": total_positions + total_holdings
            },
            "breakdown": {
                "positions_value": positions_value,
                "holdings_value": holdings_value,
                "positions_pnl": positions_pnl,
                "holdings_pnl": holdings_pnl
            },
            "largest_position": {
                "symbol": largest.symbol if largest else None,
                "value": largest.quantity * largest.ltp if largest else 0,
                "pnl": largest.pnl if largest else 0
            } if largest else None,
            "performance": {
                "best_performer": best_performer,
                "worst_performer": worst_performer
            },
            "risk_metrics": {
                "daily_pnl": risk_status.daily_pnl,
                "max_portfolio_value": config.get('risk.max_portfolio_value'),
                "utilization_percentage": (total_value / config.get('risk.max_portfolio_value') * 100)
                if config.get('risk.max_portfolio_value') > 0 else 0,
                "max_positions": config.get('risk.max_open_positions'),
                "positions_remaining": config.get('risk.max_open_positions') - total_positions
            }
        }

        logger.info(
            "Portfolio summary generated",
            total_value=total_value,
            total_pnl=total_pnl,
            positions=total_positions,
            holdings=total_holdings
        )

        return summary

    except Exception as e:
        logger.error(f"Error generating portfolio summary: {e}")
        raise


@mcp.tool()
async def get_position_by_symbol(
    symbol: str,
    exchange: str = "NSE",
    ctx: Optional[Context] = None
) -> Optional[Dict[str, Any]]:
    """
    Get position details for a specific symbol.

    Args:
        symbol: Stock symbol (e.g., "RELIANCE", "TCS")
        exchange: Exchange name (NSE or BSE), defaults to NSE

    Returns:
        Position details if found, None otherwise

    Example:
        get_position_by_symbol(symbol="RELIANCE", exchange="NSE")
    """
    logger.info(f"Fetching position for {symbol} on {exchange}")

    try:
        groww_client = ctx.request_context.groww_client

        positions = await groww_client.get_positions()

        # Find matching position
        for position in positions:
            if position.symbol == symbol and position.exchange == exchange:
                logger.info(
                    "Position found",
                    symbol=symbol,
                    quantity=position.quantity,
                    pnl=position.pnl
                )
                return position.model_dump()

        logger.info(f"No position found for {symbol} on {exchange}")
        return None

    except Exception as e:
        logger.error(f"Error fetching position: {e}", symbol=symbol)
        raise


@mcp.tool()
async def get_holding_by_symbol(
    symbol: str,
    exchange: str = "NSE",
    ctx: Optional[Context] = None
) -> Optional[Dict[str, Any]]:
    """
    Get holding details for a specific symbol.

    Args:
        symbol: Stock symbol (e.g., "RELIANCE", "TCS")
        exchange: Exchange name (NSE or BSE), defaults to NSE

    Returns:
        Holding details if found, None otherwise

    Example:
        get_holding_by_symbol(symbol="TCS", exchange="NSE")
    """
    logger.info(f"Fetching holding for {symbol} on {exchange}")

    try:
        groww_client = ctx.request_context.groww_client

        holdings = await groww_client.get_holdings()

        # Find matching holding
        for holding in holdings:
            if holding.symbol == symbol and holding.exchange == exchange:
                logger.info(
                    "Holding found",
                    symbol=symbol,
                    quantity=holding.quantity,
                    pnl=holding.pnl
                )
                return holding.model_dump()

        logger.info(f"No holding found for {symbol} on {exchange}")
        return None

    except Exception as e:
        logger.error(f"Error fetching holding: {e}", symbol=symbol)
        raise


@mcp.tool()
async def calculate_portfolio_allocation(
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Calculate portfolio allocation by stock (percentage breakdown).

    Returns:
        Allocation breakdown showing what percentage of portfolio each stock represents

    Example:
        calculate_portfolio_allocation()
    """
    logger.info("Calculating portfolio allocation")

    try:
        groww_client = ctx.request_context.groww_client

        # Get all positions and holdings
        positions = await groww_client.get_positions()
        holdings = await groww_client.get_holdings()

        all_items = positions + holdings

        # Calculate total portfolio value
        total_value = sum(item.quantity * item.ltp for item in all_items)

        if total_value == 0:
            logger.info("Portfolio is empty")
            return {
                "total_value": 0,
                "allocations": []
            }

        # Calculate allocation for each stock
        allocations = []
        for item in all_items:
            item_value = item.quantity * item.ltp
            percentage = (item_value / total_value * 100) if total_value > 0 else 0

            allocations.append({
                "symbol": item.symbol,
                "exchange": item.exchange,
                "value": item_value,
                "percentage": round(percentage, 2),
                "quantity": item.quantity,
                "type": "position" if item in positions else "holding"
            })

        # Sort by value (largest first)
        allocations.sort(key=lambda x: x["value"], reverse=True)

        result = {
            "total_value": total_value,
            "allocations": allocations,
            "diversification": {
                "number_of_stocks": len(allocations),
                "largest_allocation": allocations[0]["percentage"] if allocations else 0,
                "top_3_concentration": sum(a["percentage"] for a in allocations[:3]) if len(allocations) >= 3 else 100
            }
        }

        logger.info(
            "Portfolio allocation calculated",
            total_value=total_value,
            stocks=len(allocations)
        )

        return result

    except Exception as e:
        logger.error(f"Error calculating portfolio allocation: {e}")
        raise
