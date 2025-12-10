"""
GTT Executor - Executes GTT orders when triggered.

This module handles the execution of Good Till Triggered orders,
including risk validation, order placement, and status updates.
"""

from typing import Optional
from datetime import datetime

from .storage import GTTStorage
from ..api.models import GTTOrder, GTTStatus, Order
from ..api.exceptions import (
    GTTExecutionError, KillSwitchActive,
    OrderError, RiskManagementError
)
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class GTTExecutor:
    """
    GTT order executor.

    Responsibilities:
    - Validate GTT against risk limits
    - Place order via Groww client
    - Update GTT status
    - Handle execution errors
    - Log all executions
    """

    def __init__(self, groww_client, storage: GTTStorage, risk_manager):
        """
        Initialize GTT executor.

        Args:
            groww_client: GrowwClient instance
            storage: GTTStorage instance
            risk_manager: RiskManager instance
        """
        self.groww_client = groww_client
        self.storage = storage
        self.risk_manager = risk_manager

        # Statistics
        self.stats = {
            'executions_attempted': 0,
            'executions_succeeded': 0,
            'executions_failed': 0,
            'risk_rejections': 0,
            'kill_switch_blocks': 0
        }

        logger.info("GTT executor initialized")

    async def execute_gtt(
        self,
        gtt: GTTOrder,
        current_price: float
    ) -> Optional[Order]:
        """
        Execute GTT order.

        Process:
        1. Check kill switch
        2. Validate with risk manager
        3. Place order via Groww client
        4. Update GTT status to TRIGGERED
        5. Record order ID
        6. Handle errors appropriately

        Args:
            gtt: GTT order to execute
            current_price: Current LTP that triggered execution

        Returns:
            Order object if successful, None if failed

        Raises:
            GTTExecutionError: If execution fails
        """
        self.stats['executions_attempted'] += 1

        try:
            logger.info(
                "Executing GTT order",
                gtt_id=gtt.id,
                symbol=gtt.symbol,
                action=gtt.action,
                trigger_price=gtt.trigger_price,
                current_price=current_price,
                quantity=gtt.quantity
            )

            # 1. Check kill switch
            try:
                self.risk_manager.kill_switch.check_before_order()
            except AttributeError:
                # Kill switch not available (for backwards compatibility)
                logger.debug("Kill switch not available, skipping check")
            except KillSwitchActive as e:
                logger.error(
                    "GTT execution blocked by kill switch",
                    gtt_id=gtt.id,
                    reason=str(e)
                )

                self.stats['kill_switch_blocks'] += 1

                # Update GTT status to FAILED
                await self.storage.update_gtt_status(
                    gtt.id,
                    GTTStatus.FAILED.value,
                    error_message=f"Kill switch active: {str(e)}",
                    trigger_ltp=current_price
                )

                raise GTTExecutionError(
                    f"GTT execution blocked by kill switch: {str(e)}",
                    gtt_id=gtt.id
                )

            # 2. Validate with risk manager
            use_price = gtt.limit_price if gtt.order_type == "LIMIT" else current_price

            validation = await self.risk_manager.validate_order(
                symbol=gtt.symbol,
                quantity=gtt.quantity,
                price=use_price,
                transaction_type=gtt.action,
                order_type=gtt.order_type,
                exchange=gtt.exchange
            )

            if not validation.approved:
                logger.warning(
                    "GTT execution rejected by risk manager",
                    gtt_id=gtt.id,
                    reason=validation.reason
                )

                self.stats['risk_rejections'] += 1

                # Update GTT status to FAILED
                await self.storage.update_gtt_status(
                    gtt.id,
                    GTTStatus.FAILED.value,
                    error_message=f"Risk validation failed: {validation.reason}",
                    trigger_ltp=current_price
                )

                raise GTTExecutionError(
                    f"Risk validation failed: {validation.reason}",
                    gtt_id=gtt.id
                )

            # 3. Place order via Groww client
            order = await self._place_order(gtt, current_price)

            # 4. Update GTT status to TRIGGERED
            await self.storage.update_gtt_status(
                gtt.id,
                GTTStatus.TRIGGERED.value,
                order_id=order.order_id,
                trigger_ltp=current_price
            )

            # 5. Record order with risk manager
            await self.risk_manager.record_order(order)

            self.stats['executions_succeeded'] += 1

            logger.info(
                "GTT executed successfully",
                gtt_id=gtt.id,
                order_id=order.order_id,
                symbol=gtt.symbol,
                action=gtt.action,
                quantity=gtt.quantity,
                trigger_ltp=current_price
            )

            # Log to orders logger
            orders_logger = get_logger('orders')
            orders_logger.info(
                "GTT order executed",
                gtt_id=gtt.id,
                order_id=order.order_id,
                symbol=gtt.symbol,
                action=gtt.action,
                quantity=gtt.quantity,
                order_type=gtt.order_type,
                trigger_price=gtt.trigger_price,
                trigger_ltp=current_price,
                limit_price=gtt.limit_price
            )

            return order

        except GTTExecutionError:
            # Already handled and logged
            raise

        except Exception as e:
            logger.error(
                f"GTT execution failed with unexpected error: {e}",
                gtt_id=gtt.id,
                symbol=gtt.symbol
            )

            self.stats['executions_failed'] += 1

            # Update GTT status to FAILED
            try:
                await self.storage.update_gtt_status(
                    gtt.id,
                    GTTStatus.FAILED.value,
                    error_message=str(e),
                    trigger_ltp=current_price
                )
            except Exception as update_error:
                logger.error(f"Failed to update GTT status: {update_error}")

            raise GTTExecutionError(
                f"GTT execution failed: {str(e)}",
                gtt_id=gtt.id
            )

    async def _place_order(self, gtt: GTTOrder, current_price: float) -> Order:
        """
        Place order for GTT.

        Args:
            gtt: GTT order
            current_price: Current LTP

        Returns:
            Order object

        Raises:
            OrderError: If order placement fails
        """
        try:
            # Determine order price
            if gtt.order_type == "LIMIT":
                price = gtt.limit_price
            else:  # MARKET
                price = None

            # Place order
            order = await self.groww_client.place_order(
                symbol=gtt.symbol,
                exchange=gtt.exchange,
                transaction_type=gtt.action,
                quantity=gtt.quantity,
                order_type=gtt.order_type,
                price=price,
                product="CNC",  # Always use CNC for GTT
                segment="CASH"   # Always use CASH for GTT
            )

            logger.debug(
                "Order placed for GTT",
                gtt_id=gtt.id,
                order_id=order.order_id
            )

            return order

        except Exception as e:
            logger.error(f"Failed to place order for GTT: {e}", gtt_id=gtt.id)
            raise OrderError(f"Order placement failed: {str(e)}")

    async def retry_failed_gtt(self, gtt_id: int) -> Optional[Order]:
        """
        Retry execution of a failed GTT.

        Args:
            gtt_id: GTT order ID

        Returns:
            Order object if successful

        Raises:
            GTTExecutionError: If retry fails
        """
        try:
            # Get GTT
            gtt = await self.storage.get_gtt(gtt_id)

            # Check status
            if gtt.status != GTTStatus.FAILED.value:
                raise GTTExecutionError(
                    f"Can only retry FAILED GTTs. Current status: {gtt.status}",
                    gtt_id=gtt_id
                )

            logger.info(f"Retrying failed GTT {gtt_id}")

            # Reset to ACTIVE
            await self.storage.update_gtt_status(
                gtt_id,
                GTTStatus.ACTIVE.value,
                error_message=None
            )

            # Get current price
            ltp = await self.groww_client.get_ltp(gtt.symbol, gtt.exchange)

            # Check if trigger condition still met
            if self._should_trigger(gtt, ltp):
                return await self.execute_gtt(gtt, ltp)
            else:
                logger.info(
                    "GTT retry: Trigger condition not met, marked as ACTIVE",
                    gtt_id=gtt_id,
                    trigger_price=gtt.trigger_price,
                    current_ltp=ltp
                )
                return None

        except Exception as e:
            logger.error(f"Failed to retry GTT: {e}", gtt_id=gtt_id)
            raise GTTExecutionError(f"GTT retry failed: {str(e)}", gtt_id=gtt_id)

    def _should_trigger(self, gtt: GTTOrder, ltp: float) -> bool:
        """
        Check if GTT should trigger based on LTP.

        Trigger conditions:
        - BUY: ltp <= trigger_price (buy when price drops to or below trigger)
        - SELL: ltp >= trigger_price (sell when price rises to or above trigger)

        Args:
            gtt: GTT order
            ltp: Last traded price

        Returns:
            True if should trigger
        """
        if gtt.action == "BUY":
            return ltp <= gtt.trigger_price
        else:  # SELL
            return ltp >= gtt.trigger_price

    def get_stats(self) -> dict:
        """
        Get executor statistics.

        Returns:
            Dictionary with statistics
        """
        total_attempted = self.stats['executions_attempted']
        success_rate = (
            (self.stats['executions_succeeded'] / total_attempted * 100)
            if total_attempted > 0 else 0
        )

        return {
            **self.stats,
            'success_rate': success_rate
        }

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"GTTExecutor(attempted={self.stats['executions_attempted']}, "
            f"succeeded={self.stats['executions_succeeded']}, "
            f"failed={self.stats['executions_failed']})"
        )
