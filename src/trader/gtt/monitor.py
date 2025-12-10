"""
GTT Monitor - Background monitoring for GTT triggers.

This module runs a continuous loop checking active GTT orders
and executing them when trigger conditions are met.
"""

import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, time

from .storage import GTTStorage
from .executor import GTTExecutor
from ..api.models import GTTOrder, GTTStatus
from ..api.exceptions import GTTExecutionError, DataFetchError
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class GTTMonitor:
    """
    Background monitor for GTT orders.

    Responsibilities:
    - Run monitoring loop at regular intervals
    - Fetch active GTT orders
    - Check current LTP for each symbol
    - Trigger execution when conditions met
    - Handle market hours
    - Track monitoring statistics
    """

    def __init__(
        self,
        groww_client,
        storage: GTTStorage,
        executor: GTTExecutor,
        check_interval: int = 30
    ):
        """
        Initialize GTT monitor.

        Args:
            groww_client: GrowwClient instance
            storage: GTTStorage instance
            executor: GTTExecutor instance
            check_interval: Check interval in seconds (default: 30)
        """
        self.groww_client = groww_client
        self.storage = storage
        self.executor = executor
        self.check_interval = check_interval

        # Monitor state
        self._running: bool = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._paused: bool = False

        # Statistics
        self.stats = {
            'checks_performed': 0,
            'gtts_triggered': 0,
            'trigger_failures': 0,
            'symbols_checked': 0,
            'api_errors': 0,
            'last_check_time': None,
            'started_at': None
        }

        # Cache for symbol prices (to reduce API calls)
        self._price_cache: Dict[str, tuple[float, datetime]] = {}
        self._cache_ttl: int = 10  # Cache TTL in seconds

        logger.info(
            "GTT monitor initialized",
            check_interval=check_interval
        )

    async def start(self) -> None:
        """
        Start GTT monitoring.

        Launches background task that continuously monitors active GTTs.
        """
        if self._running:
            logger.warning("GTT monitor already running")
            return

        self._running = True
        self.stats['started_at'] = datetime.now().isoformat()

        logger.info("Starting GTT monitor")

        # Start monitoring task
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """Stop GTT monitoring."""
        if not self._running:
            logger.warning("GTT monitor not running")
            return

        logger.info("Stopping GTT monitor")

        self._running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        logger.info("GTT monitor stopped")

    def pause(self) -> None:
        """Pause GTT monitoring (stops checking but keeps loop running)."""
        if not self._running:
            logger.warning("Cannot pause - monitor not running")
            return

        self._paused = True
        logger.info("GTT monitor paused")

    def resume(self) -> None:
        """Resume GTT monitoring."""
        if not self._running:
            logger.warning("Cannot resume - monitor not running")
            return

        self._paused = False
        logger.info("GTT monitor resumed")

    async def _monitor_loop(self) -> None:
        """
        Main monitoring loop.

        Continuously checks active GTTs and triggers execution when conditions met.
        """
        logger.info("GTT monitoring loop started")

        try:
            while self._running:
                # Check if paused
                if self._paused:
                    await asyncio.sleep(self.check_interval)
                    continue

                # Check if market hours (optional - can be configured)
                if not self._is_trading_hours():
                    logger.debug("Outside trading hours, skipping GTT check")
                    await asyncio.sleep(60)  # Check every minute during off-hours
                    continue

                # Perform GTT check
                await self._check_gtts()

                # Wait for next check
                await asyncio.sleep(self.check_interval)

        except asyncio.CancelledError:
            logger.info("GTT monitoring loop cancelled")
            raise

        except Exception as e:
            logger.error(f"GTT monitoring loop error: {e}")
            # Continue monitoring despite errors
            if self._running:
                await asyncio.sleep(self.check_interval)
                await self._monitor_loop()

    async def _check_gtts(self) -> None:
        """
        Check all active GTTs and trigger if conditions met.
        """
        try:
            self.stats['checks_performed'] += 1
            self.stats['last_check_time'] = datetime.now().isoformat()

            # Get all active GTTs
            active_gtts = await self.storage.get_active_gtts()

            if not active_gtts:
                logger.debug("No active GTTs to check")
                return

            logger.debug(f"Checking {len(active_gtts)} active GTTs")

            # Group GTTs by symbol to minimize API calls
            gtts_by_symbol = self._group_by_symbol(active_gtts)

            # Check each symbol
            for symbol_key, gtts in gtts_by_symbol.items():
                symbol, exchange = symbol_key.split(':')

                try:
                    # Get current LTP
                    ltp = await self._get_ltp(symbol, exchange)

                    self.stats['symbols_checked'] += 1

                    # Check each GTT for this symbol
                    for gtt in gtts:
                        if self._should_trigger(gtt, ltp):
                            logger.info(
                                "GTT trigger condition met",
                                gtt_id=gtt.id,
                                symbol=symbol,
                                trigger_price=gtt.trigger_price,
                                current_ltp=ltp,
                                action=gtt.action
                            )

                            # Execute GTT
                            await self._execute_gtt(gtt, ltp)

                except DataFetchError as e:
                    self.stats['api_errors'] += 1
                    logger.warning(
                        f"Failed to get LTP for {symbol}: {e}",
                        symbol=symbol,
                        exchange=exchange
                    )
                    # Continue checking other symbols

                except Exception as e:
                    logger.error(
                        f"Error checking GTTs for {symbol}: {e}",
                        symbol=symbol
                    )
                    # Continue checking other symbols

        except Exception as e:
            logger.error(f"Error in GTT check: {e}")

    async def _execute_gtt(self, gtt: GTTOrder, ltp: float) -> None:
        """
        Execute triggered GTT.

        Args:
            gtt: GTT order to execute
            ltp: Current LTP that triggered execution
        """
        try:
            await self.executor.execute_gtt(gtt, ltp)

            self.stats['gtts_triggered'] += 1

            logger.info(
                "GTT executed successfully",
                gtt_id=gtt.id,
                symbol=gtt.symbol
            )

        except GTTExecutionError as e:
            self.stats['trigger_failures'] += 1

            logger.error(
                f"GTT execution failed: {e}",
                gtt_id=gtt.id,
                symbol=gtt.symbol
            )

        except Exception as e:
            self.stats['trigger_failures'] += 1

            logger.error(
                f"Unexpected error executing GTT: {e}",
                gtt_id=gtt.id,
                symbol=gtt.symbol
            )

    async def _get_ltp(self, symbol: str, exchange: str) -> float:
        """
        Get LTP with caching to reduce API calls.

        Args:
            symbol: Trading symbol
            exchange: Exchange

        Returns:
            Last traded price
        """
        cache_key = f"{symbol}:{exchange}"

        # Check cache
        if cache_key in self._price_cache:
            cached_price, cached_time = self._price_cache[cache_key]
            age = (datetime.now() - cached_time).total_seconds()

            if age < self._cache_ttl:
                logger.debug(
                    f"Using cached LTP for {symbol}",
                    age_seconds=age
                )
                return cached_price

        # Fetch fresh LTP
        ltp = await self.groww_client.get_ltp(symbol, exchange)

        # Update cache
        self._price_cache[cache_key] = (ltp, datetime.now())

        return ltp

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
            should_trigger = ltp <= gtt.trigger_price
        else:  # SELL
            should_trigger = ltp >= gtt.trigger_price

        if should_trigger:
            logger.debug(
                "GTT trigger condition check",
                gtt_id=gtt.id,
                symbol=gtt.symbol,
                action=gtt.action,
                trigger_price=gtt.trigger_price,
                ltp=ltp,
                should_trigger=should_trigger
            )

        return should_trigger

    def _group_by_symbol(self, gtts: list[GTTOrder]) -> Dict[str, list[GTTOrder]]:
        """
        Group GTTs by symbol to minimize API calls.

        Args:
            gtts: List of GTT orders

        Returns:
            Dictionary mapping "symbol:exchange" to list of GTTs
        """
        grouped = {}

        for gtt in gtts:
            key = f"{gtt.symbol}:{gtt.exchange}"
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(gtt)

        return grouped

    def _is_trading_hours(self) -> bool:
        """
        Check if currently in trading hours.

        NSE/BSE trading hours: 9:15 AM - 3:30 PM IST (Mon-Fri)

        Returns:
            True if in trading hours

        Note:
            This is a simplified check. Production code should consider:
            - Market holidays
            - Pre-market and post-market sessions
            - Different exchanges
        """
        now = datetime.now()

        # Check if weekend
        if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False

        # Check time (9:15 AM - 3:30 PM)
        current_time = now.time()
        market_open = time(9, 15)
        market_close = time(15, 30)

        # For testing/paper trading, you might want to allow 24/7
        # Comment out the time check below for 24/7 monitoring
        return market_open <= current_time <= market_close

    async def check_now(self) -> None:
        """
        Immediately check all GTTs (on-demand check).

        Useful for testing or manual triggers.
        """
        logger.info("Manual GTT check triggered")
        await self._check_gtts()

    def is_running(self) -> bool:
        """
        Check if monitor is running.

        Returns:
            True if monitor is running
        """
        return self._running

    def is_paused(self) -> bool:
        """
        Check if monitor is paused.

        Returns:
            True if monitor is paused
        """
        return self._paused

    def get_stats(self) -> Dict[str, Any]:
        """
        Get monitoring statistics.

        Returns:
            Dictionary with statistics
        """
        stats = dict(self.stats)

        # Add current state
        stats['is_running'] = self._running
        stats['is_paused'] = self._paused
        stats['cache_size'] = len(self._price_cache)

        # Calculate success rate
        total_triggers = stats['gtts_triggered'] + stats['trigger_failures']
        if total_triggers > 0:
            stats['trigger_success_rate'] = (
                stats['gtts_triggered'] / total_triggers * 100
            )
        else:
            stats['trigger_success_rate'] = 0

        # Calculate uptime
        if stats['started_at']:
            started = datetime.fromisoformat(stats['started_at'])
            uptime_seconds = (datetime.now() - started).total_seconds()
            stats['uptime_seconds'] = uptime_seconds
            stats['uptime_hours'] = uptime_seconds / 3600

        return stats

    def clear_price_cache(self) -> None:
        """Clear price cache (useful for testing or manual refresh)."""
        logger.debug(f"Clearing price cache ({len(self._price_cache)} entries)")
        self._price_cache.clear()

    def __repr__(self) -> str:
        """String representation."""
        status = "running" if self._running else "stopped"
        if self._paused:
            status += " (paused)"

        return (
            f"GTTMonitor({status}, "
            f"triggered={self.stats['gtts_triggered']}, "
            f"checks={self.stats['checks_performed']})"
        )
