"""
MCP Tools for GTT (Good Till Triggered) Order Management.

Provides tools for creating, monitoring, and managing GTT orders.
"""

from typing import Optional, Dict, Any, List

from mcp.server.fastmcp import Context

from ..server import mcp
from ...core.logging_config import get_logger

logger = get_logger(__name__)


@mcp.tool()
async def create_gtt(
    symbol: str,
    trigger_price: float,
    action: str,
    quantity: int,
    order_type: str = "LIMIT",
    limit_price: Optional[float] = None,
    exchange: str = "NSE",
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Create a GTT (Good Till Triggered) order.

    GTT orders are monitored continuously and automatically execute when
    the trigger condition is met:
    - BUY GTT: Executes when LTP <= trigger_price (buy on dip)
    - SELL GTT: Executes when LTP >= trigger_price (sell on rise)

    Args:
        symbol: Stock symbol (e.g., "RELIANCE", "TCS")
        trigger_price: Price at which to trigger the order
        action: "BUY" or "SELL"
        quantity: Number of shares
        order_type: "LIMIT" or "MARKET" (default: LIMIT)
        limit_price: Limit price for order execution (required for LIMIT orders)
        exchange: Exchange name (NSE or BSE), defaults to NSE

    Returns:
        GTT order confirmation with GTT ID

    Example:
        create_gtt(
            symbol="RELIANCE",
            trigger_price=2400.00,
            action="BUY",
            quantity=1,
            order_type="LIMIT",
            limit_price=2400.00,
            exchange="NSE"
        )
    """
    logger.info(
        f"Creating {action} GTT for {symbol}",
        trigger_price=trigger_price,
        quantity=quantity
    )

    try:
        gtt_storage = ctx.request_context.gtt_storage
        config = ctx.request_context.config

        # Validate parameters
        if order_type == "LIMIT" and limit_price is None:
            raise ValueError("LIMIT order requires limit_price parameter")

        # For MARKET orders, use trigger price as limit price
        if order_type == "MARKET":
            limit_price = trigger_price

        # Create GTT in database
        gtt_id = await gtt_storage.create_gtt(
            symbol=symbol,
            exchange=exchange,
            trigger_price=trigger_price,
            order_type=order_type,
            action=action,
            quantity=quantity,
            limit_price=limit_price
        )

        logger.info(
            "GTT created successfully",
            gtt_id=gtt_id,
            symbol=symbol,
            trigger_price=trigger_price,
            action=action
        )

        result = {
            "gtt_id": gtt_id,
            "symbol": symbol,
            "exchange": exchange,
            "trigger_price": trigger_price,
            "action": action,
            "quantity": quantity,
            "order_type": order_type,
            "limit_price": limit_price,
            "status": "ACTIVE",
            "message": f"GTT order created. Will {action} {quantity} shares of {symbol} when price {'falls to' if action == 'BUY' else 'rises to'} ₹{trigger_price}",
            "paper_mode": config.is_paper_mode()
        }

        return result

    except Exception as e:
        logger.error(f"Error creating GTT: {e}", symbol=symbol)
        raise


@mcp.tool()
async def list_gtts(
    status: Optional[str] = None,
    symbol: Optional[str] = None,
    ctx: Optional[Context] = None
) -> List[Dict[str, Any]]:
    """
    List GTT orders with optional filtering.

    Args:
        status: Filter by status - "ACTIVE", "TRIGGERED", "COMPLETED", "CANCELLED", "FAILED", or None for all
        symbol: Filter by symbol (e.g., "RELIANCE"), or None for all symbols

    Returns:
        List of GTT orders matching the filters

    Example:
        list_gtts(status="ACTIVE")
        list_gtts(symbol="RELIANCE")
        list_gtts()  # All GTTs
    """
    logger.info(f"Listing GTTs (status={status}, symbol={symbol})")

    try:
        gtt_storage = ctx.request_context.gtt_storage

        if status and status.upper() == "ACTIVE":
            # Get only active GTTs
            gtts = await gtt_storage.get_active_gtts()
        elif symbol:
            # Filter by symbol
            gtts = await gtt_storage.get_gtts_by_symbol(symbol)
        else:
            # Get all GTTs
            gtts = await gtt_storage.get_all_gtts()

            # Filter by status if specified
            if status:
                gtts = [gtt for gtt in gtts if gtt.status.upper() == status.upper()]

        logger.info(f"Found {len(gtts)} GTT orders")

        return [gtt.model_dump() for gtt in gtts]

    except Exception as e:
        logger.error(f"Error listing GTTs: {e}")
        raise


@mcp.tool()
async def get_gtt(
    gtt_id: int,
    ctx: Optional[Context] = None
) -> Optional[Dict[str, Any]]:
    """
    Get details of a specific GTT order.

    Args:
        gtt_id: GTT order ID

    Returns:
        GTT order details if found, None otherwise

    Example:
        get_gtt(gtt_id=123)
    """
    logger.info(f"Fetching GTT {gtt_id}")

    try:
        gtt_storage = ctx.request_context.gtt_storage

        gtt = await gtt_storage.get_gtt(gtt_id)

        if gtt:
            logger.info(
                "GTT found",
                gtt_id=gtt_id,
                symbol=gtt.symbol,
                status=gtt.status
            )
            return gtt.model_dump()
        else:
            logger.info(f"GTT {gtt_id} not found")
            return None

    except Exception as e:
        logger.error(f"Error fetching GTT: {e}", gtt_id=gtt_id)
        raise


@mcp.tool()
async def cancel_gtt(
    gtt_id: int,
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Cancel an active GTT order.

    Args:
        gtt_id: GTT order ID to cancel

    Returns:
        Cancellation confirmation

    Example:
        cancel_gtt(gtt_id=123)
    """
    logger.info(f"Cancelling GTT {gtt_id}")

    try:
        gtt_storage = ctx.request_context.gtt_storage

        # Get GTT to verify it exists and is cancellable
        gtt = await gtt_storage.get_gtt(gtt_id)

        if not gtt:
            raise ValueError(f"GTT {gtt_id} not found")

        if gtt.status != "ACTIVE":
            raise ValueError(f"Cannot cancel GTT {gtt_id} - status is {gtt.status}, must be ACTIVE")

        # Cancel the GTT
        await gtt_storage.cancel_gtt(gtt_id)

        logger.info(
            "GTT cancelled successfully",
            gtt_id=gtt_id,
            symbol=gtt.symbol
        )

        return {
            "gtt_id": gtt_id,
            "symbol": gtt.symbol,
            "status": "CANCELLED",
            "message": f"GTT order {gtt_id} for {gtt.symbol} has been cancelled"
        }

    except Exception as e:
        logger.error(f"Error cancelling GTT: {e}", gtt_id=gtt_id)
        raise


@mcp.tool()
async def get_gtt_statistics(
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Get GTT system statistics and summary.

    Returns:
        Statistics including:
        - Total GTT count by status
        - Active GTTs count
        - Success/failure rates
        - Recent triggers

    Example:
        get_gtt_statistics()
    """
    logger.info("Fetching GTT statistics")

    try:
        gtt_storage = ctx.request_context.gtt_storage
        gtt_monitor = ctx.request_context.gtt_monitor

        # Get statistics from storage
        stats = await gtt_storage.get_statistics()

        # Add monitoring status
        result = {
            "monitoring": {
                "is_running": gtt_monitor.is_running(),
                "check_interval_seconds": gtt_monitor.check_interval if hasattr(gtt_monitor, 'check_interval') else 30
            },
            "totals": {
                "total_gtts": stats.get("total", 0),
                "active": stats.get("active", 0),
                "triggered": stats.get("triggered", 0),
                "completed": stats.get("completed", 0),
                "cancelled": stats.get("cancelled", 0),
                "failed": stats.get("failed", 0)
            },
            "performance": {
                "success_rate": stats.get("success_rate", 0),
                "completion_rate": stats.get("completion_rate", 0)
            }
        }

        logger.info(
            "GTT statistics fetched",
            total_gtts=result["totals"]["total_gtts"],
            active=result["totals"]["active"]
        )

        return result

    except Exception as e:
        logger.error(f"Error fetching GTT statistics: {e}")
        raise


@mcp.tool()
async def trigger_gtt_manually(
    gtt_id: int,
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Manually trigger a GTT order (bypass price check).

    USE WITH CAUTION: This will execute the GTT immediately regardless of price.

    Args:
        gtt_id: GTT order ID to trigger

    Returns:
        Execution result

    Example:
        trigger_gtt_manually(gtt_id=123)
    """
    logger.warning(f"Manual GTT trigger requested for GTT {gtt_id}")

    try:
        gtt_storage = ctx.request_context.gtt_storage
        gtt_executor = ctx.request_context.gtt_executor
        groww_client = ctx.request_context.groww_client

        # Get GTT
        gtt = await gtt_storage.get_gtt(gtt_id)

        if not gtt:
            raise ValueError(f"GTT {gtt_id} not found")

        if gtt.status != "ACTIVE":
            raise ValueError(f"Cannot trigger GTT {gtt_id} - status is {gtt.status}, must be ACTIVE")

        # Get current price for logging
        current_price = await groww_client.get_ltp(gtt.symbol, gtt.exchange)

        logger.warning(
            "Manually triggering GTT",
            gtt_id=gtt_id,
            symbol=gtt.symbol,
            trigger_price=gtt.trigger_price,
            current_price=current_price
        )

        # Execute GTT
        result = await gtt_executor.execute_gtt(gtt, current_price)

        logger.info(
            "GTT manually triggered",
            gtt_id=gtt_id,
            order_id=result.get("order_id") if isinstance(result, dict) else None
        )

        return {
            "gtt_id": gtt_id,
            "symbol": gtt.symbol,
            "trigger_type": "manual",
            "current_price": current_price,
            "execution_result": result if isinstance(result, dict) else {"order_id": result},
            "message": f"GTT {gtt_id} manually triggered at price ₹{current_price}"
        }

    except Exception as e:
        logger.error(f"Error manually triggering GTT: {e}", gtt_id=gtt_id)
        raise


@mcp.tool()
async def pause_gtt_monitoring(
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Pause GTT monitoring (stops checking for trigger conditions).

    USE WITH CAUTION: GTTs will not execute while monitoring is paused.

    Returns:
        Pause confirmation

    Example:
        pause_gtt_monitoring()
    """
    logger.warning("Pausing GTT monitoring")

    try:
        gtt_monitor = ctx.request_context.gtt_monitor

        gtt_monitor.pause()

        logger.warning("GTT monitoring paused")

        return {
            "status": "paused",
            "message": "GTT monitoring has been paused. GTTs will not trigger until monitoring is resumed.",
            "warning": "Remember to resume monitoring with resume_gtt_monitoring()"
        }

    except Exception as e:
        logger.error(f"Error pausing GTT monitoring: {e}")
        raise


@mcp.tool()
async def resume_gtt_monitoring(
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Resume GTT monitoring (restarts checking for trigger conditions).

    Returns:
        Resume confirmation

    Example:
        resume_gtt_monitoring()
    """
    logger.info("Resuming GTT monitoring")

    try:
        gtt_monitor = ctx.request_context.gtt_monitor

        gtt_monitor.resume()

        logger.info("GTT monitoring resumed")

        return {
            "status": "running",
            "message": "GTT monitoring has been resumed. Active GTTs will now be monitored."
        }

    except Exception as e:
        logger.error(f"Error resuming GTT monitoring: {e}")
        raise


@mcp.tool()
async def check_gtt_trigger_condition(
    gtt_id: int,
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Check if a GTT's trigger condition is currently met (without executing).

    Args:
        gtt_id: GTT order ID to check

    Returns:
        Trigger condition status with current price and analysis

    Example:
        check_gtt_trigger_condition(gtt_id=123)
    """
    logger.info(f"Checking trigger condition for GTT {gtt_id}")

    try:
        gtt_storage = ctx.request_context.gtt_storage
        groww_client = ctx.request_context.groww_client

        # Get GTT
        gtt = await gtt_storage.get_gtt(gtt_id)

        if not gtt:
            raise ValueError(f"GTT {gtt_id} not found")

        # Get current price
        current_price = await groww_client.get_ltp(gtt.symbol, gtt.exchange)

        # Check trigger condition
        should_trigger = False
        if gtt.action.upper() == "BUY":
            should_trigger = current_price <= gtt.trigger_price
            condition = f"LTP ({current_price}) <= Trigger ({gtt.trigger_price})"
        else:  # SELL
            should_trigger = current_price >= gtt.trigger_price
            condition = f"LTP ({current_price}) >= Trigger ({gtt.trigger_price})"

        # Calculate distance to trigger
        distance = abs(current_price - gtt.trigger_price)
        distance_pct = (distance / gtt.trigger_price * 100) if gtt.trigger_price > 0 else 0

        result = {
            "gtt_id": gtt_id,
            "symbol": gtt.symbol,
            "exchange": gtt.exchange,
            "status": gtt.status,
            "action": gtt.action,
            "trigger_price": gtt.trigger_price,
            "current_price": current_price,
            "should_trigger": should_trigger,
            "condition": condition,
            "distance_to_trigger": {
                "absolute": round(distance, 2),
                "percentage": round(distance_pct, 2)
            },
            "message": f"{'TRIGGER CONDITION MET' if should_trigger else 'Condition not met'} - {condition}"
        }

        logger.info(
            "Trigger condition checked",
            gtt_id=gtt_id,
            should_trigger=should_trigger,
            current_price=current_price
        )

        return result

    except Exception as e:
        logger.error(f"Error checking trigger condition: {e}", gtt_id=gtt_id)
        raise
