"""
GTT Storage - SQLite database for GTT orders.

This module manages persistent storage of Good Till Triggered (GTT) orders,
which are custom trigger-based orders that execute when price conditions are met.
"""

import sqlite3
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from ..api.models import GTTOrder, GTTStatus
from ..api.exceptions import GTTError, GTTNotFoundError
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class GTTStorage:
    """
    SQLite storage for GTT orders.

    Responsibilities:
    - Create and manage database schema
    - Store GTT orders with all parameters
    - Query active, triggered, and completed GTTs
    - Update GTT status and execution details
    - Provide transaction support
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize GTT storage.

        Args:
            db_path: Path to SQLite database file (default: data/gtt_orders.db)
        """
        if db_path is None:
            # Default to data/gtt_orders.db
            db_path = Path(__file__).parent.parent.parent.parent / "data" / "gtt_orders.db"

        self.db_path = Path(db_path)

        # Ensure data directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Connection will be created per thread/task
        self._conn: Optional[sqlite3.Connection] = None

        logger.info(f"GTT storage initialized at {self.db_path}")

        # Initialize database schema
        asyncio.create_task(self._initialize_db())

    async def _initialize_db(self) -> None:
        """Initialize database schema."""
        try:
            conn = await self._get_connection()

            # Create GTT orders table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS gtt_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    trigger_price REAL NOT NULL,
                    order_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    limit_price REAL,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    triggered_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    order_id TEXT,
                    error_message TEXT,
                    trigger_ltp REAL,
                    notes TEXT
                )
            """)

            # Create indexes for common queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status
                ON gtt_orders(status)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_symbol
                ON gtt_orders(symbol, exchange)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at
                ON gtt_orders(created_at DESC)
            """)

            conn.commit()

            logger.info("GTT database schema initialized")

        except Exception as e:
            logger.error(f"Failed to initialize GTT database: {e}")
            raise GTTError(f"Database initialization failed: {str(e)}")

    async def _get_connection(self) -> sqlite3.Connection:
        """
        Get database connection.

        Returns:
            SQLite connection

        Note:
            Creates new connection if needed. SQLite connections are not thread-safe,
            so we use one connection per async task context.
        """
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row  # Enable column access by name

        return self._conn

    async def create_gtt(
        self,
        symbol: str,
        exchange: str,
        trigger_price: float,
        order_type: str,
        action: str,
        quantity: int,
        limit_price: Optional[float] = None,
        notes: Optional[str] = None
    ) -> GTTOrder:
        """
        Create new GTT order.

        Args:
            symbol: Trading symbol
            exchange: Exchange (NSE/BSE)
            trigger_price: Price at which to trigger
            order_type: LIMIT or MARKET
            action: BUY or SELL
            quantity: Number of shares
            limit_price: Limit price for LIMIT orders
            notes: Optional notes

        Returns:
            Created GTTOrder with ID

        Raises:
            GTTError: If creation fails
        """
        try:
            conn = await self._get_connection()

            cursor = conn.execute("""
                INSERT INTO gtt_orders (
                    symbol, exchange, trigger_price, order_type, action,
                    quantity, limit_price, status, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol, exchange, trigger_price, order_type, action,
                quantity, limit_price, GTTStatus.ACTIVE.value, notes
            ))

            conn.commit()
            gtt_id = cursor.lastrowid

            logger.info(
                "GTT order created",
                gtt_id=gtt_id,
                symbol=symbol,
                action=action,
                trigger_price=trigger_price,
                quantity=quantity
            )

            # Fetch and return the created GTT
            return await self.get_gtt(gtt_id)

        except Exception as e:
            logger.error(f"Failed to create GTT: {e}")
            raise GTTError(f"GTT creation failed: {str(e)}")

    async def get_gtt(self, gtt_id: int) -> GTTOrder:
        """
        Get GTT order by ID.

        Args:
            gtt_id: GTT order ID

        Returns:
            GTTOrder object

        Raises:
            GTTNotFoundError: If GTT not found
        """
        try:
            conn = await self._get_connection()

            cursor = conn.execute("""
                SELECT * FROM gtt_orders WHERE id = ?
            """, (gtt_id,))

            row = cursor.fetchone()

            if not row:
                raise GTTNotFoundError(f"GTT order {gtt_id} not found", gtt_id=gtt_id)

            return self._row_to_gtt(row)

        except GTTNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to get GTT: {e}", gtt_id=gtt_id)
            raise GTTError(f"Failed to retrieve GTT: {str(e)}", gtt_id=gtt_id)

    async def get_active_gtts(self) -> List[GTTOrder]:
        """
        Get all active GTT orders.

        Returns:
            List of active GTTOrder objects
        """
        try:
            conn = await self._get_connection()

            cursor = conn.execute("""
                SELECT * FROM gtt_orders
                WHERE status = ?
                ORDER BY created_at ASC
            """, (GTTStatus.ACTIVE.value,))

            rows = cursor.fetchall()

            gtts = [self._row_to_gtt(row) for row in rows]

            logger.debug(f"Retrieved {len(gtts)} active GTT orders")

            return gtts

        except Exception as e:
            logger.error(f"Failed to get active GTTs: {e}")
            raise GTTError(f"Failed to retrieve active GTTs: {str(e)}")

    async def get_gtts_by_symbol(
        self,
        symbol: str,
        exchange: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[GTTOrder]:
        """
        Get GTT orders by symbol.

        Args:
            symbol: Trading symbol
            exchange: Optional exchange filter
            status: Optional status filter

        Returns:
            List of GTTOrder objects
        """
        try:
            conn = await self._get_connection()

            query = "SELECT * FROM gtt_orders WHERE symbol = ?"
            params = [symbol]

            if exchange:
                query += " AND exchange = ?"
                params.append(exchange)

            if status:
                query += " AND status = ?"
                params.append(status)

            query += " ORDER BY created_at DESC"

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_gtt(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to get GTTs by symbol: {e}", symbol=symbol)
            raise GTTError(f"Failed to retrieve GTTs: {str(e)}")

    async def get_all_gtts(
        self,
        limit: Optional[int] = None,
        status: Optional[str] = None
    ) -> List[GTTOrder]:
        """
        Get all GTT orders.

        Args:
            limit: Optional limit on number of results
            status: Optional status filter

        Returns:
            List of GTTOrder objects
        """
        try:
            conn = await self._get_connection()

            query = "SELECT * FROM gtt_orders"
            params = []

            if status:
                query += " WHERE status = ?"
                params.append(status)

            query += " ORDER BY created_at DESC"

            if limit:
                query += " LIMIT ?"
                params.append(limit)

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_gtt(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to get all GTTs: {e}")
            raise GTTError(f"Failed to retrieve GTTs: {str(e)}")

    async def update_gtt_status(
        self,
        gtt_id: int,
        status: str,
        order_id: Optional[str] = None,
        error_message: Optional[str] = None,
        trigger_ltp: Optional[float] = None
    ) -> GTTOrder:
        """
        Update GTT status.

        Args:
            gtt_id: GTT order ID
            status: New status (TRIGGERED, COMPLETED, CANCELLED, FAILED)
            order_id: Optional Groww order ID (when triggered)
            error_message: Optional error message (when failed)
            trigger_ltp: Optional LTP at trigger time

        Returns:
            Updated GTTOrder

        Raises:
            GTTNotFoundError: If GTT not found
        """
        try:
            conn = await self._get_connection()

            # Build update query dynamically
            updates = ["status = ?"]
            params = [status]

            # Set timestamp based on status
            if status == GTTStatus.TRIGGERED.value:
                updates.append("triggered_at = CURRENT_TIMESTAMP")
            elif status in [GTTStatus.COMPLETED.value, GTTStatus.FAILED.value, GTTStatus.CANCELLED.value]:
                updates.append("completed_at = CURRENT_TIMESTAMP")

            if order_id:
                updates.append("order_id = ?")
                params.append(order_id)

            if error_message:
                updates.append("error_message = ?")
                params.append(error_message)

            if trigger_ltp is not None:
                updates.append("trigger_ltp = ?")
                params.append(trigger_ltp)

            params.append(gtt_id)

            query = f"""
                UPDATE gtt_orders
                SET {', '.join(updates)}
                WHERE id = ?
            """

            cursor = conn.execute(query, params)
            conn.commit()

            if cursor.rowcount == 0:
                raise GTTNotFoundError(f"GTT order {gtt_id} not found", gtt_id=gtt_id)

            logger.info(
                "GTT status updated",
                gtt_id=gtt_id,
                status=status,
                order_id=order_id
            )

            return await self.get_gtt(gtt_id)

        except GTTNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to update GTT status: {e}", gtt_id=gtt_id)
            raise GTTError(f"GTT status update failed: {str(e)}", gtt_id=gtt_id)

    async def cancel_gtt(self, gtt_id: int) -> GTTOrder:
        """
        Cancel GTT order.

        Args:
            gtt_id: GTT order ID

        Returns:
            Updated GTTOrder with CANCELLED status

        Raises:
            GTTNotFoundError: If GTT not found
            GTTError: If GTT cannot be cancelled (already triggered/completed)
        """
        try:
            # Check current status
            gtt = await self.get_gtt(gtt_id)

            if gtt.status != GTTStatus.ACTIVE.value:
                raise GTTError(
                    f"Cannot cancel GTT with status {gtt.status}. Only ACTIVE GTTs can be cancelled.",
                    gtt_id=gtt_id
                )

            # Update to CANCELLED
            updated_gtt = await self.update_gtt_status(gtt_id, GTTStatus.CANCELLED.value)

            logger.info("GTT cancelled", gtt_id=gtt_id)

            return updated_gtt

        except (GTTNotFoundError, GTTError):
            raise
        except Exception as e:
            logger.error(f"Failed to cancel GTT: {e}", gtt_id=gtt_id)
            raise GTTError(f"GTT cancellation failed: {str(e)}", gtt_id=gtt_id)

    async def delete_gtt(self, gtt_id: int) -> bool:
        """
        Permanently delete GTT order.

        WARNING: This is permanent. Prefer cancel_gtt() for normal operations.

        Args:
            gtt_id: GTT order ID

        Returns:
            True if deleted

        Raises:
            GTTNotFoundError: If GTT not found
        """
        try:
            conn = await self._get_connection()

            cursor = conn.execute("DELETE FROM gtt_orders WHERE id = ?", (gtt_id,))
            conn.commit()

            if cursor.rowcount == 0:
                raise GTTNotFoundError(f"GTT order {gtt_id} not found", gtt_id=gtt_id)

            logger.warning("GTT deleted permanently", gtt_id=gtt_id)

            return True

        except GTTNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to delete GTT: {e}", gtt_id=gtt_id)
            raise GTTError(f"GTT deletion failed: {str(e)}", gtt_id=gtt_id)

    async def get_statistics(self) -> Dict[str, Any]:
        """
        Get GTT statistics.

        Returns:
            Dictionary with statistics
        """
        try:
            conn = await self._get_connection()

            # Count by status
            cursor = conn.execute("""
                SELECT status, COUNT(*) as count
                FROM gtt_orders
                GROUP BY status
            """)

            status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

            # Get total count
            cursor = conn.execute("SELECT COUNT(*) as total FROM gtt_orders")
            total = cursor.fetchone()['total']

            # Get recent activity (last 24 hours)
            cursor = conn.execute("""
                SELECT COUNT(*) as count
                FROM gtt_orders
                WHERE created_at >= datetime('now', '-1 day')
            """)
            recent_created = cursor.fetchone()['count']

            cursor = conn.execute("""
                SELECT COUNT(*) as count
                FROM gtt_orders
                WHERE triggered_at >= datetime('now', '-1 day')
            """)
            recent_triggered = cursor.fetchone()['count']

            return {
                'total': total,
                'by_status': status_counts,
                'active': status_counts.get(GTTStatus.ACTIVE.value, 0),
                'triggered': status_counts.get(GTTStatus.TRIGGERED.value, 0),
                'completed': status_counts.get(GTTStatus.COMPLETED.value, 0),
                'cancelled': status_counts.get(GTTStatus.CANCELLED.value, 0),
                'failed': status_counts.get(GTTStatus.FAILED.value, 0),
                'recent_24h': {
                    'created': recent_created,
                    'triggered': recent_triggered
                }
            }

        except Exception as e:
            logger.error(f"Failed to get GTT statistics: {e}")
            return {}

    def _row_to_gtt(self, row: sqlite3.Row) -> GTTOrder:
        """
        Convert database row to GTTOrder.

        Args:
            row: Database row

        Returns:
            GTTOrder object
        """
        return GTTOrder(
            id=row['id'],
            symbol=row['symbol'],
            exchange=row['exchange'],
            trigger_price=row['trigger_price'],
            order_type=row['order_type'],
            action=row['action'],
            quantity=row['quantity'],
            limit_price=row['limit_price'],
            status=row['status'],
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
            triggered_at=datetime.fromisoformat(row['triggered_at']) if row['triggered_at'] else None,
            completed_at=datetime.fromisoformat(row['completed_at']) if row['completed_at'] else None,
            order_id=row['order_id'],
            error_message=row['error_message']
        )

    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("GTT storage connection closed")

    def __repr__(self) -> str:
        """String representation."""
        return f"GTTStorage(db_path={self.db_path})"
