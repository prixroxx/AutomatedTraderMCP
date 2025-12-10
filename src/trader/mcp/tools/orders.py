"""
MCP Tools for Order Management.

Provides tools for placing, canceling, and monitoring orders with full risk validation.
"""

from typing import Optional, Dict, Any, List

from mcp.server.fastmcp import Context

from ..server import mcp
from ...core.logging_config import get_logger
from ...api.exceptions import OrderError, RiskError

logger = get_logger(__name__)


@mcp.tool()
async def place_order(
    symbol: str,
    transaction_type: str,
    quantity: int,
    order_type: str = "LIMIT",
    price: Optional[float] = None,
    trigger_price: Optional[float] = None,
    exchange: str = "NSE",
    product: str = "CNC",
    segment: str = "EQUITY",
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Place a new order with full risk validation.

    This is the primary order placement tool. All orders go through:
    1. Kill switch check
    2. Risk manager validation (7 layers)
    3. Hard limit enforcement
    4. Paper mode check (if enabled)

    Args:
        symbol: Stock symbol (e.g., "RELIANCE", "TCS")
        transaction_type: "BUY" or "SELL"
        quantity: Number of shares
        order_type: Order type - "LIMIT", "MARKET", "SL", or "SL-M"
        price: Limit price (required for LIMIT and SL orders)
        trigger_price: Trigger price (required for SL and SL-M orders)
        exchange: Exchange name (NSE or BSE), defaults to NSE
        product: Product type - "CNC" (delivery) or "INTRADAY", defaults to CNC
        segment: Market segment - "EQUITY" (default), NOT "FNO" (forbidden)

    Returns:
        Order confirmation with order_id, status, and details

    Example:
        place_order(
            symbol="RELIANCE",
            transaction_type="BUY",
            quantity=1,
            order_type="LIMIT",
            price=2500.00,
            exchange="NSE"
        )
    """
    logger.info(
        f"Placing {transaction_type} order for {symbol}",
        quantity=quantity,
        order_type=order_type,
        price=price
    )

    try:
        # Get components from context
        groww_client = ctx.request_context.groww_client
        risk_manager = ctx.request_context.risk_manager
        kill_switch = ctx.request_context.kill_switch
        config = ctx.request_context.config

        # 1. Check kill switch
        if kill_switch.is_active():
            error_msg = "Kill switch is ACTIVE - trading halted. Cannot place order."
            logger.error(error_msg)
            raise OrderError(error_msg)

        # 2. Validate order type and price requirements
        if order_type in ["LIMIT", "SL"] and price is None:
            raise OrderError(f"{order_type} order requires price parameter")

        if order_type in ["SL", "SL-M"] and trigger_price is None:
            raise OrderError(f"{order_type} order requires trigger_price parameter")

        # Use current market price for MARKET orders
        if order_type == "MARKET":
            ltp = await groww_client.get_ltp(symbol, exchange)
            price = ltp
            logger.info(f"Using market price for MARKET order: {price}")

        # 3. Risk validation
        validation = await risk_manager.validate_order(
            symbol=symbol,
            quantity=quantity,
            price=price,
            transaction_type=transaction_type
        )

        if not validation.approved:
            error_msg = f"Order rejected by risk manager: {validation.reason}"
            logger.warning(error_msg, symbol=symbol, quantity=quantity)
            raise RiskError(error_msg)

        logger.info("Order passed risk validation")

        # 4. Place order via Groww client
        order = await groww_client.place_order(
            symbol=symbol,
            exchange=exchange,
            transaction_type=transaction_type,
            quantity=quantity,
            order_type=order_type,
            price=price,
            trigger_price=trigger_price,
            product=product,
            segment=segment
        )

        # 5. Record order with risk manager
        await risk_manager.record_order(order)

        logger.info(
            "Order placed successfully",
            order_id=order.order_id,
            symbol=symbol,
            quantity=quantity,
            price=price,
            paper_mode=config.is_paper_mode()
        )

        result = order.model_dump()
        result["paper_mode"] = config.is_paper_mode()

        if config.is_paper_mode():
            result["warning"] = "PAPER MODE - Order simulated, not sent to exchange"

        return result

    except (OrderError, RiskError) as e:
        logger.error(f"Order placement failed: {e}", symbol=symbol)
        raise
    except Exception as e:
        logger.error(f"Unexpected error placing order: {e}", symbol=symbol)
        raise


@mcp.tool()
async def cancel_order(
    order_id: str,
    segment: str = "EQUITY",
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Cancel a pending order.

    Args:
        order_id: Order ID to cancel
        segment: Market segment (default: EQUITY)

    Returns:
        Cancellation confirmation

    Example:
        cancel_order(order_id="123456789", segment="EQUITY")
    """
    logger.info(f"Cancelling order {order_id}")

    try:
        groww_client = ctx.request_context.groww_client
        config = ctx.request_context.config

        result = await groww_client.cancel_order(order_id, segment)

        logger.info(
            "Order cancelled successfully",
            order_id=order_id,
            paper_mode=config.is_paper_mode()
        )

        return {
            "order_id": order_id,
            "status": "CANCELLED",
            "message": result,
            "paper_mode": config.is_paper_mode()
        }

    except Exception as e:
        logger.error(f"Error cancelling order: {e}", order_id=order_id)
        raise


@mcp.tool()
async def get_order_status(
    order_id: str,
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Get status of an order.

    Args:
        order_id: Order ID to check

    Returns:
        Order status and details

    Example:
        get_order_status(order_id="123456789")
    """
    logger.info(f"Fetching status for order {order_id}")

    try:
        groww_client = ctx.request_context.groww_client

        status = await groww_client.get_order_status(order_id)

        logger.info(
            "Order status fetched",
            order_id=order_id,
            status=status.get("status")
        )

        return status

    except Exception as e:
        logger.error(f"Error fetching order status: {e}", order_id=order_id)
        raise


@mcp.tool()
async def get_risk_status(
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Get current risk metrics and trading limits.

    Returns comprehensive risk information including:
    - Daily P&L
    - Open positions count
    - Daily order count
    - Available limits
    - Kill switch status
    - Paper mode status

    Returns:
        Risk status with all metrics and limits

    Example:
        get_risk_status()
    """
    logger.info("Fetching risk status")

    try:
        risk_manager = ctx.request_context.risk_manager
        kill_switch = ctx.request_context.kill_switch
        config = ctx.request_context.config

        # Get risk status from manager
        status = await risk_manager.get_status()

        # Add kill switch and config info
        result = {
            "daily_pnl": status.daily_pnl,
            "open_positions": status.open_positions,
            "daily_order_count": status.daily_order_count,
            "kill_switch_active": kill_switch.is_active(),
            "paper_mode": config.is_paper_mode(),
            "limits": {
                "max_portfolio_value": config.get('risk.max_portfolio_value'),
                "max_position_size": config.get('risk.max_position_size'),
                "max_daily_loss": config.get('risk.max_daily_loss'),
                "max_open_positions": config.get('risk.max_open_positions'),
                "max_single_order": config.hard_limits['MAX_SINGLE_ORDER_VALUE'],
                "max_daily_orders": config.hard_limits['MAX_DAILY_ORDERS']
            },
            "available": {
                "can_place_orders": not kill_switch.is_active(),
                "positions_available": config.get('risk.max_open_positions') - status.open_positions,
                "orders_remaining_today": config.hard_limits['MAX_DAILY_ORDERS'] - status.daily_order_count
            }
        }

        logger.info("Risk status fetched successfully")

        return result

    except Exception as e:
        logger.error(f"Error fetching risk status: {e}")
        raise


@mcp.tool()
async def activate_kill_switch(
    reason: str,
    message: Optional[str] = None,
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Manually activate the kill switch to halt all trading.

    USE WITH CAUTION: This will stop all trading immediately.

    Args:
        reason: Reason for activation (e.g., "manual", "emergency", "testing")
        message: Optional detailed message explaining the activation

    Returns:
        Kill switch activation confirmation

    Example:
        activate_kill_switch(reason="manual", message="Market volatility too high")
    """
    logger.warning(f"Manual kill switch activation requested: {reason}")

    try:
        kill_switch = ctx.request_context.kill_switch

        kill_switch.activate(reason=reason, message=message or "Manual activation via MCP")

        logger.critical(
            "KILL SWITCH ACTIVATED",
            reason=reason,
            message=message
        )

        return {
            "status": "activated",
            "reason": reason,
            "message": message,
            "warning": "All trading has been halted. Use deactivate_kill_switch to resume after cooldown."
        }

    except Exception as e:
        logger.error(f"Error activating kill switch: {e}")
        raise


@mcp.tool()
async def deactivate_kill_switch(
    admin_approval: str,
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Deactivate the kill switch to resume trading.

    Requires:
    - Admin approval code (from config)
    - 60-minute cooldown period has passed

    Args:
        admin_approval: Admin approval code for deactivation

    Returns:
        Kill switch deactivation confirmation or error

    Example:
        deactivate_kill_switch(admin_approval="your_admin_code")
    """
    logger.warning("Kill switch deactivation requested")

    try:
        kill_switch = ctx.request_context.kill_switch

        success = kill_switch.deactivate(admin_approval=admin_approval)

        if success:
            logger.info("Kill switch deactivated successfully")
            return {
                "status": "deactivated",
                "message": "Trading resumed. Kill switch monitoring continues."
            }
        else:
            logger.warning("Kill switch deactivation failed - invalid approval or cooldown not met")
            return {
                "status": "failed",
                "error": "Invalid approval code or cooldown period not met (60 minutes required)"
            }

    except Exception as e:
        logger.error(f"Error deactivating kill switch: {e}")
        raise


@mcp.tool()
async def get_order_book(
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Get today's order summary and statistics.

    Returns:
        Order book summary with count and statistics

    Example:
        get_order_book()
    """
    logger.info("Fetching order book summary")

    try:
        risk_manager = ctx.request_context.risk_manager

        # Access today's orders (private attribute)
        todays_orders = risk_manager._daily_orders if hasattr(risk_manager, '_daily_orders') else []

        logger.info(f"Order book summary fetched: {len(todays_orders)} orders today")

        return {
            "daily_order_count": len(todays_orders),
            "orders": [order.model_dump() for order in todays_orders],
            "note": "Showing today's orders tracked by risk manager. For complete order history, use Groww API directly."
        }

    except Exception as e:
        logger.error(f"Error fetching order book: {e}")
        raise
