"""
Kill Switch for emergency trading halt.

This module implements an automatic kill switch that monitors
dangerous conditions and halts all trading when triggered.
Manual intervention required to resume trading.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from collections import deque

from ..api.exceptions import KillSwitchActive
from ..core.logging_config import get_logger
from ..core.config import get_config

logger = get_logger(__name__)


class KillSwitchCondition:
    """Kill switch trigger condition."""
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    CONSECUTIVE_LOSSES = "consecutive_losses"
    API_ERROR_RATE = "api_error_rate"
    NETWORK_FAILURE = "network_failure"
    MANUAL_TRIGGER = "manual_trigger"


class KillSwitch:
    """
    Emergency kill switch for trading system.

    Monitors dangerous conditions and automatically halts trading when:
    - Daily loss exceeds hard limit (₹5k default)
    - 5+ consecutive losing trades
    - API error rate > 30%
    - Network failure > 60 seconds
    - Manual trigger

    Recovery requires:
    - Manual restart
    - 60-minute cooldown (configurable)
    - Admin approval code
    """

    def __init__(self, risk_manager, config=None):
        """
        Initialize kill switch.

        Args:
            risk_manager: RiskManager instance for monitoring
            config: Configuration object (loads default if not provided)
        """
        self.risk_manager = risk_manager
        self.config = config or get_config()

        # Kill switch state
        self._active: bool = False
        self._reason: Optional[str] = None
        self._activated_at: Optional[datetime] = None
        self._activation_count: int = 0

        # Monitoring state
        self._monitoring: bool = False
        self._monitor_task: Optional[asyncio.Task] = None

        # Tracking for conditions
        self._consecutive_losses: int = 0
        self._api_call_history: deque = deque(maxlen=100)  # Last 100 API calls
        self._network_failure_start: Optional[datetime] = None

        # Load configuration
        self._load_config()

        # Statistics
        self.stats = {
            'activations': 0,
            'deactivations': 0,
            'manual_triggers': 0,
            'auto_triggers': 0,
            'conditions_checked': 0
        }

        logger.info(
            "Kill switch initialized",
            daily_loss_threshold=self.daily_loss_threshold,
            consecutive_loss_threshold=self.consecutive_loss_threshold,
            api_error_rate_threshold=self.api_error_rate_threshold,
            cooldown_minutes=self.cooldown_minutes
        )

    def _load_config(self) -> None:
        """Load kill switch configuration."""
        # Hard limits
        hard_limits = self.config.hard_limits
        self.daily_loss_threshold = hard_limits.get('MAX_DAILY_LOSS_HARD', 5000)

        # Kill switch conditions
        kill_switch_config = self.config.get('kill_switch', {})
        self.consecutive_loss_threshold = kill_switch_config.get('consecutive_loss_threshold', 5)
        self.api_error_rate_threshold = kill_switch_config.get('api_error_rate_threshold', 0.3)  # 30%
        self.network_timeout_seconds = kill_switch_config.get('network_timeout_seconds', 60)
        self.check_interval_seconds = kill_switch_config.get('check_interval_seconds', 30)

        # Recovery protocol
        recovery_config = self.config.get('kill_switch', {}).get('recovery_protocol', {})
        self.cooldown_minutes = recovery_config.get('cooldown_period_minutes', 60)
        self.approval_code = recovery_config.get('approval_code', 'RESUME_TRADING_2024')

        logger.debug(
            "Kill switch config loaded",
            thresholds={
                'daily_loss': self.daily_loss_threshold,
                'consecutive_losses': self.consecutive_loss_threshold,
                'api_error_rate': self.api_error_rate_threshold,
                'network_timeout': self.network_timeout_seconds
            },
            recovery={
                'cooldown_minutes': self.cooldown_minutes
            }
        )

    def activate(
        self,
        reason: str,
        message: Optional[str] = None,
        condition: str = KillSwitchCondition.MANUAL_TRIGGER
    ) -> None:
        """
        Activate kill switch to halt all trading.

        Args:
            reason: Primary reason for activation
            message: Additional context message
            condition: Condition that triggered activation
        """
        if self._active:
            logger.warning("Kill switch already active", reason=self._reason)
            return

        self._active = True
        self._reason = reason
        self._activated_at = datetime.now()
        self._activation_count += 1

        self.stats['activations'] += 1

        if condition == KillSwitchCondition.MANUAL_TRIGGER:
            self.stats['manual_triggers'] += 1
        else:
            self.stats['auto_triggers'] += 1

        # CRITICAL event logging
        logger.critical(
            "🚨 KILL SWITCH ACTIVATED 🚨",
            reason=reason,
            message=message,
            condition=condition,
            activated_at=self._activated_at.isoformat(),
            activation_count=self._activation_count,
            event_type="kill_switch_activated"
        )

        # Log to risk event logger
        risk_logger = get_logger('risk_events')
        risk_logger.critical(
            "KILL SWITCH ACTIVATED - ALL TRADING HALTED",
            reason=reason,
            message=message,
            condition=condition,
            activated_at=self._activated_at.isoformat()
        )

    def deactivate(self, admin_approval: str) -> bool:
        """
        Deactivate kill switch to resume trading.

        Requires:
        - Correct approval code
        - Cooldown period elapsed

        Args:
            admin_approval: Admin approval code

        Returns:
            True if deactivation successful

        Raises:
            KillSwitchActive: If deactivation not allowed
        """
        if not self._active:
            logger.warning("Kill switch not active, ignoring deactivation")
            return False

        # Check approval code
        if admin_approval != self.approval_code:
            logger.error(
                "Kill switch deactivation failed: invalid approval code",
                event_type="unauthorized_deactivation_attempt"
            )
            raise KillSwitchActive(
                "Invalid approval code. Cannot deactivate kill switch.",
                activated_at=self._activated_at.isoformat() if self._activated_at else None
            )

        # Check cooldown period
        if self._activated_at:
            elapsed = datetime.now() - self._activated_at
            cooldown_delta = timedelta(minutes=self.cooldown_minutes)

            if elapsed < cooldown_delta:
                remaining = cooldown_delta - elapsed
                remaining_minutes = remaining.total_seconds() / 60

                logger.warning(
                    "Kill switch cooldown not elapsed",
                    elapsed_minutes=elapsed.total_seconds() / 60,
                    required_minutes=self.cooldown_minutes,
                    remaining_minutes=remaining_minutes
                )

                raise KillSwitchActive(
                    f"Cooldown period not elapsed. Wait {remaining_minutes:.1f} more minutes.",
                    activated_at=self._activated_at.isoformat()
                )

        # Deactivate
        previous_reason = self._reason

        self._active = False
        self._reason = None
        self._activated_at = None

        self.stats['deactivations'] += 1

        logger.warning(
            "🟢 Kill switch deactivated - Trading resumed",
            previous_reason=previous_reason,
            event_type="kill_switch_deactivated"
        )

        # Log to risk event logger
        risk_logger = get_logger('risk_events')
        risk_logger.warning(
            "KILL SWITCH DEACTIVATED - TRADING RESUMED",
            previous_reason=previous_reason,
            total_activation_time_minutes=(datetime.now() - self._activated_at).total_seconds() / 60 if self._activated_at else 0
        )

        return True

    def is_active(self) -> bool:
        """
        Check if kill switch is active.

        Returns:
            True if kill switch is active
        """
        return self._active

    def check_before_order(self) -> None:
        """
        Check kill switch before placing order.

        Raises:
            KillSwitchActive: If kill switch is active
        """
        if self._active:
            logger.error(
                "Order blocked by active kill switch",
                reason=self._reason,
                activated_at=self._activated_at.isoformat() if self._activated_at else None
            )

            raise KillSwitchActive(
                self._reason or "Kill switch active",
                activated_at=self._activated_at.isoformat() if self._activated_at else None
            )

    async def start_monitoring(self) -> None:
        """
        Start background monitoring of kill switch conditions.

        Runs continuously checking for trigger conditions.
        """
        if self._monitoring:
            logger.warning("Kill switch monitoring already running")
            return

        self._monitoring = True

        logger.info(
            "Starting kill switch monitoring",
            check_interval_seconds=self.check_interval_seconds
        )

        # Start monitoring task
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop_monitoring(self) -> None:
        """Stop background monitoring."""
        if not self._monitoring:
            return

        logger.info("Stopping kill switch monitoring")

        self._monitoring = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        logger.info("Kill switch monitoring stopped")

    async def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        logger.info("Kill switch monitoring loop started")

        try:
            while self._monitoring:
                await self._check_conditions()
                await asyncio.sleep(self.check_interval_seconds)

        except asyncio.CancelledError:
            logger.info("Kill switch monitoring cancelled")
            raise

        except Exception as e:
            logger.error(f"Kill switch monitoring error: {e}")
            # Continue monitoring despite errors
            if self._monitoring:
                await asyncio.sleep(self.check_interval_seconds)
                await self._monitor_loop()

    async def _check_conditions(self) -> None:
        """
        Check all kill switch trigger conditions.

        Activates kill switch if any condition is met.
        """
        if self._active:
            return  # Already active

        self.stats['conditions_checked'] += 1

        try:
            # 1. Check daily loss limit
            risk_status = await self.risk_manager.get_status()

            if risk_status.daily_pnl < 0:
                abs_loss = abs(risk_status.daily_pnl)

                if abs_loss >= self.daily_loss_threshold:
                    self.activate(
                        f"Daily loss limit breached: ₹{abs_loss:.2f} >= ₹{self.daily_loss_threshold}",
                        message="Automatic activation due to excessive daily loss",
                        condition=KillSwitchCondition.DAILY_LOSS_LIMIT
                    )
                    return

            # 2. Check consecutive losses
            if self._consecutive_losses >= self.consecutive_loss_threshold:
                self.activate(
                    f"Consecutive loss limit breached: {self._consecutive_losses} >= {self.consecutive_loss_threshold}",
                    message="Automatic activation due to consecutive losses",
                    condition=KillSwitchCondition.CONSECUTIVE_LOSSES
                )
                return

            # 3. Check API error rate
            if len(self._api_call_history) >= 20:  # Need minimum sample
                error_rate = self._calculate_api_error_rate()

                if error_rate >= self.api_error_rate_threshold:
                    self.activate(
                        f"API error rate exceeded: {error_rate:.1%} >= {self.api_error_rate_threshold:.1%}",
                        message="Automatic activation due to high API error rate",
                        condition=KillSwitchCondition.API_ERROR_RATE
                    )
                    return

            # 4. Check network failure duration
            if self._network_failure_start:
                duration = (datetime.now() - self._network_failure_start).total_seconds()

                if duration >= self.network_timeout_seconds:
                    self.activate(
                        f"Network failure duration exceeded: {duration:.0f}s >= {self.network_timeout_seconds}s",
                        message="Automatic activation due to prolonged network failure",
                        condition=KillSwitchCondition.NETWORK_FAILURE
                    )
                    return

        except Exception as e:
            logger.error(f"Error checking kill switch conditions: {e}")

    def record_trade_result(self, profit: float) -> None:
        """
        Record trade result for consecutive loss tracking.

        Args:
            profit: Trade profit (negative for loss)
        """
        if profit < 0:
            self._consecutive_losses += 1
            logger.debug(
                "Consecutive loss recorded",
                consecutive_losses=self._consecutive_losses,
                threshold=self.consecutive_loss_threshold
            )
        else:
            if self._consecutive_losses > 0:
                logger.debug(
                    "Consecutive loss streak broken",
                    previous_streak=self._consecutive_losses
                )
            self._consecutive_losses = 0

    def record_api_call(self, success: bool) -> None:
        """
        Record API call result for error rate tracking.

        Args:
            success: True if API call succeeded
        """
        self._api_call_history.append({
            'timestamp': datetime.now(),
            'success': success
        })

    def record_network_failure(self, is_failure: bool) -> None:
        """
        Record network failure state.

        Args:
            is_failure: True if network is failing
        """
        if is_failure:
            if not self._network_failure_start:
                self._network_failure_start = datetime.now()
                logger.warning("Network failure detected")
        else:
            if self._network_failure_start:
                duration = (datetime.now() - self._network_failure_start).total_seconds()
                logger.info(f"Network recovered after {duration:.0f}s")
                self._network_failure_start = None

    def _calculate_api_error_rate(self) -> float:
        """
        Calculate API error rate from recent history.

        Returns:
            Error rate as decimal (0.0 to 1.0)
        """
        if not self._api_call_history:
            return 0.0

        # Look at last 50 calls
        recent_calls = list(self._api_call_history)[-50:]
        errors = sum(1 for call in recent_calls if not call['success'])

        return errors / len(recent_calls)

    def get_status(self) -> Dict[str, Any]:
        """
        Get kill switch status.

        Returns:
            Dictionary with status information
        """
        status = {
            'active': self._active,
            'reason': self._reason,
            'activated_at': self._activated_at.isoformat() if self._activated_at else None,
            'activation_count': self._activation_count,
            'monitoring': self._monitoring
        }

        if self._active and self._activated_at:
            elapsed = datetime.now() - self._activated_at
            cooldown_remaining = max(0, self.cooldown_minutes * 60 - elapsed.total_seconds())

            status.update({
                'elapsed_seconds': elapsed.total_seconds(),
                'cooldown_remaining_seconds': cooldown_remaining,
                'can_deactivate': cooldown_remaining == 0
            })

        # Add current condition values
        status.update({
            'conditions': {
                'consecutive_losses': self._consecutive_losses,
                'consecutive_loss_threshold': self.consecutive_loss_threshold,
                'api_error_rate': self._calculate_api_error_rate(),
                'api_error_rate_threshold': self.api_error_rate_threshold,
                'network_failure_duration': (
                    (datetime.now() - self._network_failure_start).total_seconds()
                    if self._network_failure_start else 0
                ),
                'network_timeout_seconds': self.network_timeout_seconds
            }
        })

        return status

    def get_stats(self) -> Dict[str, Any]:
        """
        Get kill switch statistics.

        Returns:
            Dictionary with statistics
        """
        return {
            **self.stats,
            'current_status': self.get_status()
        }

    def reset_for_testing(self) -> None:
        """Reset kill switch state (for testing only)."""
        logger.warning("⚠️  Kill switch reset for testing")

        self._active = False
        self._reason = None
        self._activated_at = None
        self._consecutive_losses = 0
        self._api_call_history.clear()
        self._network_failure_start = None

    def __repr__(self) -> str:
        """String representation."""
        status = "ACTIVE" if self._active else "INACTIVE"
        return f"KillSwitch({status}, reason='{self._reason}')"
