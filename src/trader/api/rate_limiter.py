"""
Rate limiter for Groww API calls using token bucket algorithm.

This module implements rate limiting to ensure we stay within
Groww API limits and avoid being throttled or blocked.
"""

import asyncio
from datetime import datetime, timedelta
from collections import deque
from typing import Literal
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """
    Token bucket rate limiter for API calls.

    Tracks three separate rate limit categories as per Groww API:
    - orders: Order placement/modification/cancellation (15/sec max, we use 10)
    - live_data: Real-time quotes, LTP, OHLC (10/sec max, we use 8)
    - non_trading: Account info, positions, historical data (20/sec max, we use 15)

    Uses conservative limits below API maximums for safety.
    """

    def __init__(
        self,
        orders_per_sec: int = 10,
        data_per_sec: int = 8,
        non_trading_per_sec: int = 15
    ):
        """
        Initialize rate limiter.

        Args:
            orders_per_sec: Maximum orders per second (default: 10)
            data_per_sec: Maximum live data requests per second (default: 8)
            non_trading_per_sec: Maximum non-trading requests per second (default: 15)
        """
        self.limits = {
            'orders': orders_per_sec,
            'live_data': data_per_sec,
            'non_trading': non_trading_per_sec
        }

        # Track recent requests with timestamps
        self.request_history = {
            'orders': deque(maxlen=100),
            'live_data': deque(maxlen=100),
            'non_trading': deque(maxlen=100)
        }

        # Locks for thread safety
        self._locks = {
            'orders': asyncio.Lock(),
            'live_data': asyncio.Lock(),
            'non_trading': asyncio.Lock()
        }

        # Statistics
        self.stats = {
            'orders': {'total': 0, 'delayed': 0},
            'live_data': {'total': 0, 'delayed': 0},
            'non_trading': {'total': 0, 'delayed': 0}
        }

        logger.info(
            "Rate limiter initialized",
            orders_per_sec=orders_per_sec,
            data_per_sec=data_per_sec,
            non_trading_per_sec=non_trading_per_sec
        )

    async def acquire(
        self,
        category: Literal['orders', 'live_data', 'non_trading']
    ) -> None:
        """
        Acquire rate limit token for category.

        Blocks (sleeps) if rate limit would be exceeded.

        Args:
            category: Category of API call
        """
        async with self._locks[category]:
            now = datetime.now()
            one_second_ago = now - timedelta(seconds=1)

            # Remove requests older than 1 second
            history = self.request_history[category]
            while history and history[0] < one_second_ago:
                history.popleft()

            # Check if we've hit the limit
            if len(history) >= self.limits[category]:
                # Calculate wait time
                oldest_request = history[0]
                wait_time = 1.0 - (now - oldest_request).total_seconds()

                if wait_time > 0:
                    self.stats[category]['delayed'] += 1

                    logger.debug(
                        f"Rate limit hit for {category}, waiting {wait_time:.2f}s",
                        category=category,
                        wait_seconds=wait_time,
                        current_rate=len(history),
                        limit=self.limits[category]
                    )

                    await asyncio.sleep(wait_time)

                    # Remove old requests after waiting
                    now = datetime.now()
                    one_second_ago = now - timedelta(seconds=1)
                    while history and history[0] < one_second_ago:
                        history.popleft()

            # Record this request
            history.append(now)
            self.stats[category]['total'] += 1

    def get_current_rate(
        self,
        category: Literal['orders', 'live_data', 'non_trading']
    ) -> float:
        """
        Get current request rate for category (requests/second).

        Args:
            category: Category to check

        Returns:
            Current rate in requests per second
        """
        now = datetime.now()
        one_second_ago = now - timedelta(seconds=1)

        history = self.request_history[category]
        recent_requests = sum(1 for ts in history if ts >= one_second_ago)

        return recent_requests

    def get_stats(self) -> dict:
        """
        Get rate limiter statistics.

        Returns:
            Dictionary with statistics for each category
        """
        return {
            category: {
                'total_requests': stats['total'],
                'delayed_requests': stats['delayed'],
                'current_rate': self.get_current_rate(category),
                'limit': self.limits[category],
                'delay_percentage': (
                    (stats['delayed'] / stats['total'] * 100)
                    if stats['total'] > 0 else 0
                )
            }
            for category, stats in self.stats.items()
        }

    def is_near_limit(
        self,
        category: Literal['orders', 'live_data', 'non_trading'],
        threshold: float = 0.8
    ) -> bool:
        """
        Check if current rate is near the limit.

        Args:
            category: Category to check
            threshold: Threshold as fraction of limit (0.8 = 80%)

        Returns:
            True if current rate >= threshold * limit
        """
        current_rate = self.get_current_rate(category)
        limit = self.limits[category]

        return current_rate >= (limit * threshold)

    def reset_stats(self) -> None:
        """Reset statistics (useful for testing or periodic resets)."""
        for category in self.stats:
            self.stats[category] = {'total': 0, 'delayed': 0}

        logger.info("Rate limiter statistics reset")

    def __repr__(self) -> str:
        """String representation of rate limiter."""
        return (
            f"RateLimiter("
            f"orders={self.limits['orders']}/s, "
            f"live_data={self.limits['live_data']}/s, "
            f"non_trading={self.limits['non_trading']}/s)"
        )
