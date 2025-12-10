"""
Risk Manager for trading system.

This module implements comprehensive risk management including:
- Multi-layer order validation
- Position size limits
- Daily loss limits
- Order count limits
- P&L tracking
- Risk status monitoring
"""

from datetime import datetime, date
from typing import Optional, Dict, List, Any
from pydantic import BaseModel

from ..api.models import Order, Position, RiskMetrics
from ..api.exceptions import (
    RiskManagementError, PositionLimitExceeded,
    DailyLossLimitExceeded, InvalidOrderError
)
from ..core.logging_config import get_logger
from ..core.config import get_config

logger = get_logger(__name__)


class OrderValidation(BaseModel):
    """Order validation result."""
    approved: bool
    reason: Optional[str] = None
    limit_type: Optional[str] = None
    current_value: Optional[float] = None
    limit_value: Optional[float] = None


class RiskManager:
    """
    Risk management system.

    Responsibilities:
    - Validate orders against all risk limits
    - Track daily P&L
    - Monitor position counts and sizes
    - Enforce hard limits
    - Prevent excessive losses
    - Coordinate with kill switch
    """

    def __init__(self, groww_client, config=None):
        """
        Initialize risk manager.

        Args:
            groww_client: GrowwClient instance for portfolio queries
            config: Configuration object (loads default if not provided)
        """
        self.groww_client = groww_client
        self.config = config or get_config()

        # Daily tracking (resets at market open)
        self._current_day: Optional[date] = None
        self._daily_pnl: float = 0.0
        self._daily_order_count: int = 0
        self._daily_orders: List[Order] = []

        # Position tracking
        self._open_positions: Dict[str, Position] = {}
        self._position_count: int = 0

        # Statistics
        self.stats = {
            'orders_validated': 0,
            'orders_approved': 0,
            'orders_rejected': 0,
            'rejection_reasons': {}
        }

        # Load limits from config
        self._load_limits()

        logger.info(
            "Risk manager initialized",
            max_portfolio_value=self.max_portfolio_value,
            max_position_size=self.max_position_size,
            max_daily_loss=self.max_daily_loss,
            max_open_positions=self.max_open_positions
        )

    def _load_limits(self) -> None:
        """Load risk limits from configuration."""
        # Soft limits (from user config)
        risk_config = self.config.get('risk', {})
        self.max_portfolio_value = risk_config.get('max_portfolio_value', 50000)
        self.max_position_size = risk_config.get('max_position_size', 5000)
        self.max_daily_loss = risk_config.get('max_daily_loss', 2000)
        self.max_open_positions = risk_config.get('max_open_positions', 3)

        # Hard limits (non-overridable)
        hard_limits = self.config.hard_limits
        self.max_single_order_value = hard_limits.get('MAX_SINGLE_ORDER_VALUE', 10000)
        self.max_daily_orders = hard_limits.get('MAX_DAILY_ORDERS', 15)
        self.max_daily_loss_hard = hard_limits.get('MAX_DAILY_LOSS_HARD', 5000)
        self.forbidden_segments = hard_limits.get('FORBIDDEN_SEGMENTS', [])
        self.forbidden_products = hard_limits.get('FORBIDDEN_PRODUCTS', [])

        logger.debug(
            "Risk limits loaded",
            soft_limits={
                'max_portfolio_value': self.max_portfolio_value,
                'max_position_size': self.max_position_size,
                'max_daily_loss': self.max_daily_loss,
                'max_open_positions': self.max_open_positions
            },
            hard_limits={
                'max_single_order_value': self.max_single_order_value,
                'max_daily_orders': self.max_daily_orders,
                'max_daily_loss_hard': self.max_daily_loss_hard
            }
        )

    async def validate_order(
        self,
        symbol: str,
        quantity: int,
        price: float,
        transaction_type: str,
        order_type: str = "LIMIT",
        exchange: str = "NSE",
        product: str = "CNC",
        segment: str = "CASH"
    ) -> OrderValidation:
        """
        Validate order against all risk constraints.

        Validation pipeline:
        1. Check day rollover (reset daily counters if new day)
        2. Check single order value vs MAX_SINGLE_ORDER_VALUE
        3. Check position size vs max_position_size
        4. Check daily order count vs MAX_DAILY_ORDERS
        5. Check open positions vs max_open_positions (for BUY)
        6. Check daily loss vs max_daily_loss and max_daily_loss_hard
        7. Check forbidden segments and products

        Args:
            symbol: Trading symbol
            quantity: Order quantity
            price: Order price
            transaction_type: BUY or SELL
            order_type: Order type
            exchange: Exchange
            product: Product type
            segment: Market segment

        Returns:
            OrderValidation with approval status and reason
        """
        self.stats['orders_validated'] += 1

        try:
            # 1. Check day rollover
            self._check_day_rollover()

            order_value = quantity * price

            logger.info(
                "Validating order",
                symbol=symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                price=price,
                order_value=order_value
            )

            # 2. Check single order value (HARD LIMIT)
            if order_value > self.max_single_order_value:
                reason = (
                    f"Single order value ₹{order_value:.2f} exceeds "
                    f"hard limit ₹{self.max_single_order_value}"
                )
                return self._reject_order(
                    reason,
                    'max_single_order_value',
                    order_value,
                    self.max_single_order_value
                )

            # 3. Check position size (for BUY orders)
            if transaction_type == "BUY":
                if order_value > self.max_position_size:
                    reason = (
                        f"Position size ₹{order_value:.2f} exceeds "
                        f"limit ₹{self.max_position_size}"
                    )
                    return self._reject_order(
                        reason,
                        'max_position_size',
                        order_value,
                        self.max_position_size
                    )

            # 4. Check daily order count (HARD LIMIT)
            if self._daily_order_count >= self.max_daily_orders:
                reason = (
                    f"Daily order limit reached: {self._daily_order_count}/"
                    f"{self.max_daily_orders}"
                )
                return self._reject_order(
                    reason,
                    'max_daily_orders',
                    self._daily_order_count,
                    self.max_daily_orders
                )

            # 5. Check open positions (for BUY orders)
            if transaction_type == "BUY":
                # Check if opening a new position
                if symbol not in self._open_positions:
                    if self._position_count >= self.max_open_positions:
                        reason = (
                            f"Maximum open positions reached: {self._position_count}/"
                            f"{self.max_open_positions}"
                        )
                        return self._reject_order(
                            reason,
                            'max_open_positions',
                            self._position_count,
                            self.max_open_positions
                        )

            # 6. Check daily loss limits
            if self._daily_pnl < 0:
                abs_loss = abs(self._daily_pnl)

                # Check hard limit first
                if abs_loss >= self.max_daily_loss_hard:
                    reason = (
                        f"Hard daily loss limit breached: ₹{abs_loss:.2f} >= "
                        f"₹{self.max_daily_loss_hard} (KILL SWITCH TERRITORY)"
                    )
                    return self._reject_order(
                        reason,
                        'max_daily_loss_hard',
                        abs_loss,
                        self.max_daily_loss_hard
                    )

                # Check soft limit
                if abs_loss >= self.max_daily_loss:
                    reason = (
                        f"Daily loss limit reached: ₹{abs_loss:.2f} >= "
                        f"₹{self.max_daily_loss}"
                    )
                    return self._reject_order(
                        reason,
                        'max_daily_loss',
                        abs_loss,
                        self.max_daily_loss
                    )

            # 7. Check forbidden segments and products
            if segment in self.forbidden_segments:
                reason = f"Segment '{segment}' is forbidden by hard limits"
                return self._reject_order(
                    reason,
                    'forbidden_segment',
                    segment,
                    None
                )

            if product in self.forbidden_products:
                reason = f"Product '{product}' is forbidden by hard limits"
                return self._reject_order(
                    reason,
                    'forbidden_product',
                    product,
                    None
                )

            # All checks passed
            self.stats['orders_approved'] += 1

            logger.info(
                "Order approved by risk manager",
                symbol=symbol,
                order_value=order_value,
                daily_orders=self._daily_order_count,
                open_positions=self._position_count,
                daily_pnl=self._daily_pnl
            )

            return OrderValidation(approved=True)

        except Exception as e:
            logger.error(f"Error during order validation: {e}", symbol=symbol)
            return self._reject_order(
                f"Validation error: {str(e)}",
                'validation_error',
                None,
                None
            )

    async def record_order(self, order: Order) -> None:
        """
        Record order for tracking.

        Args:
            order: Order object to record
        """
        self._check_day_rollover()

        self._daily_orders.append(order)
        self._daily_order_count += 1

        logger.info(
            "Order recorded",
            order_id=order.order_id,
            symbol=order.symbol,
            transaction_type=order.transaction_type,
            daily_order_count=self._daily_order_count
        )

    async def update_daily_pnl(self) -> float:
        """
        Update daily P&L from current positions.

        Returns:
            Current daily P&L

        Raises:
            Exception: If P&L calculation fails
        """
        try:
            logger.debug("Updating daily P&L")

            # Get current positions from Groww
            positions = await self.groww_client.get_positions()

            # Update position tracking
            self._open_positions = {
                pos.symbol: pos for pos in positions
            }
            self._position_count = len(positions)

            # Calculate daily P&L
            daily_pnl = sum(
                pos.pnl if pos.pnl is not None else 0.0
                for pos in positions
            )

            self._daily_pnl = daily_pnl

            logger.info(
                "Daily P&L updated",
                daily_pnl=daily_pnl,
                open_positions=self._position_count,
                positions=[pos.symbol for pos in positions]
            )

            return daily_pnl

        except Exception as e:
            logger.error(f"Failed to update daily P&L: {e}")
            raise

    async def get_status(self) -> RiskMetrics:
        """
        Get current risk status.

        Returns:
            RiskMetrics with current risk metrics
        """
        self._check_day_rollover()

        # Update P&L
        try:
            await self.update_daily_pnl()
        except Exception as e:
            logger.warning(f"Could not update P&L for status: {e}")

        # Calculate available capital
        used_capital = sum(
            pos.quantity * pos.average_price
            for pos in self._open_positions.values()
        )
        available_capital = self.max_portfolio_value - used_capital

        # Check health
        warnings = []
        is_healthy = True

        # Check daily loss
        if self._daily_pnl < 0:
            abs_loss = abs(self._daily_pnl)
            loss_pct = (abs_loss / self.max_daily_loss) * 100

            if abs_loss >= self.max_daily_loss_hard:
                warnings.append(f"CRITICAL: Hard loss limit breached (₹{abs_loss:.2f})")
                is_healthy = False
            elif abs_loss >= self.max_daily_loss * 0.8:
                warnings.append(f"WARNING: Daily loss at {loss_pct:.0f}% of limit")
                if abs_loss >= self.max_daily_loss:
                    is_healthy = False

        # Check order count
        if self._daily_order_count >= self.max_daily_orders * 0.8:
            order_pct = (self._daily_order_count / self.max_daily_orders) * 100
            warnings.append(f"WARNING: Daily orders at {order_pct:.0f}% of limit")
            if self._daily_order_count >= self.max_daily_orders:
                is_healthy = False

        # Check position count
        if self._position_count >= self.max_open_positions:
            warnings.append(f"WARNING: Maximum positions reached")
            is_healthy = False

        return RiskMetrics(
            daily_pnl=self._daily_pnl,
            open_positions=self._position_count,
            max_positions=self.max_open_positions,
            used_capital=used_capital,
            available_capital=available_capital,
            daily_loss_limit=self.max_daily_loss,
            daily_order_count=self._daily_order_count,
            max_daily_orders=self.max_daily_orders,
            kill_switch_active=False,  # Updated by kill switch
            is_healthy=is_healthy,
            warnings=warnings
        )

    def _check_day_rollover(self) -> None:
        """Check if new trading day and reset counters."""
        today = date.today()

        if self._current_day != today:
            logger.info(
                "Day rollover detected, resetting daily counters",
                previous_day=self._current_day,
                new_day=today,
                previous_pnl=self._daily_pnl,
                previous_orders=self._daily_order_count
            )

            # Reset daily counters
            self._current_day = today
            self._daily_pnl = 0.0
            self._daily_order_count = 0
            self._daily_orders = []

            # Keep position tracking but log it
            logger.info(
                "Positions carried over",
                position_count=self._position_count,
                positions=list(self._open_positions.keys())
            )

    def _reject_order(
        self,
        reason: str,
        limit_type: str,
        current_value: Any,
        limit_value: Any
    ) -> OrderValidation:
        """
        Reject order and log reason.

        Args:
            reason: Rejection reason
            limit_type: Type of limit exceeded
            current_value: Current value
            limit_value: Limit value

        Returns:
            OrderValidation with rejection details
        """
        self.stats['orders_rejected'] += 1

        # Track rejection reasons
        if limit_type not in self.stats['rejection_reasons']:
            self.stats['rejection_reasons'][limit_type] = 0
        self.stats['rejection_reasons'][limit_type] += 1

        logger.warning(
            "Order rejected by risk manager",
            reason=reason,
            limit_type=limit_type,
            current_value=current_value,
            limit_value=limit_value,
            event_type="order_rejected"
        )

        return OrderValidation(
            approved=False,
            reason=reason,
            limit_type=limit_type,
            current_value=current_value,
            limit_value=limit_value
        )

    def get_stats(self) -> Dict[str, Any]:
        """
        Get risk manager statistics.

        Returns:
            Dictionary with statistics
        """
        approval_rate = (
            (self.stats['orders_approved'] / self.stats['orders_validated'] * 100)
            if self.stats['orders_validated'] > 0
            else 0
        )

        return {
            'orders_validated': self.stats['orders_validated'],
            'orders_approved': self.stats['orders_approved'],
            'orders_rejected': self.stats['orders_rejected'],
            'approval_rate': approval_rate,
            'rejection_reasons': self.stats['rejection_reasons'],
            'current_state': {
                'current_day': str(self._current_day),
                'daily_pnl': self._daily_pnl,
                'daily_order_count': self._daily_order_count,
                'open_positions': self._position_count,
                'position_symbols': list(self._open_positions.keys())
            }
        }

    def reset_daily_counters(self) -> None:
        """Manually reset daily counters (for testing or emergency)."""
        logger.warning(
            "Manually resetting daily counters",
            previous_pnl=self._daily_pnl,
            previous_orders=self._daily_order_count
        )

        self._current_day = date.today()
        self._daily_pnl = 0.0
        self._daily_order_count = 0
        self._daily_orders = []

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"RiskManager(day={self._current_day}, pnl=₹{self._daily_pnl:.2f}, "
            f"orders={self._daily_order_count}/{self.max_daily_orders}, "
            f"positions={self._position_count}/{self.max_open_positions})"
        )
