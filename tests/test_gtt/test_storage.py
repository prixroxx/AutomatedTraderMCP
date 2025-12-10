"""
Tests for GTT Storage.

Tests cover:
- Database initialization
- GTT creation
- GTT retrieval
- Status updates
- Cancellation
- Queries
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from src.trader.gtt.storage import GTTStorage
from src.trader.api.models import GTTStatus
from src.trader.api.exceptions import GTTNotFoundError, GTTError


@pytest.fixture
async def storage():
    """Create test storage with temporary database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_gtt.db"
        storage = GTTStorage(db_path)

        # Wait for initialization
        await storage._initialize_db()

        yield storage

        # Cleanup
        await storage.close()


class TestStorageInitialization:
    """Test storage initialization."""

    @pytest.mark.asyncio
    async def test_database_creation(self, storage):
        """Test database file is created."""
        assert storage.db_path.exists()

    @pytest.mark.asyncio
    async def test_schema_creation(self, storage):
        """Test database schema is created."""
        conn = await storage._get_connection()

        # Check table exists
        cursor = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='gtt_orders'
        """)

        assert cursor.fetchone() is not None


class TestGTTCreation:
    """Test GTT creation."""

    @pytest.mark.asyncio
    async def test_create_basic_gtt(self, storage):
        """Test creating a basic GTT order."""
        gtt = await storage.create_gtt(
            symbol="RELIANCE",
            exchange="NSE",
            trigger_price=2500.0,
            order_type="LIMIT",
            action="BUY",
            quantity=1,
            limit_price=2490.0
        )

        assert gtt.id is not None
        assert gtt.symbol == "RELIANCE"
        assert gtt.exchange == "NSE"
        assert gtt.trigger_price == 2500.0
        assert gtt.status == GTTStatus.ACTIVE.value

    @pytest.mark.asyncio
    async def test_create_market_gtt(self, storage):
        """Test creating MARKET order GTT."""
        gtt = await storage.create_gtt(
            symbol="TCS",
            exchange="NSE",
            trigger_price=3500.0,
            order_type="MARKET",
            action="SELL",
            quantity=1
        )

        assert gtt.order_type == "MARKET"
        assert gtt.limit_price is None

    @pytest.mark.asyncio
    async def test_create_with_notes(self, storage):
        """Test creating GTT with notes."""
        gtt = await storage.create_gtt(
            symbol="INFY",
            exchange="NSE",
            trigger_price=1500.0,
            order_type="LIMIT",
            action="BUY",
            quantity=2,
            limit_price=1490.0,
            notes="Test GTT with notes"
        )

        assert gtt.id is not None


class TestGTTRetrieval:
    """Test GTT retrieval."""

    @pytest.mark.asyncio
    async def test_get_gtt_by_id(self, storage):
        """Test retrieving GTT by ID."""
        created = await storage.create_gtt(
            symbol="RELIANCE",
            exchange="NSE",
            trigger_price=2500.0,
            order_type="LIMIT",
            action="BUY",
            quantity=1,
            limit_price=2490.0
        )

        retrieved = await storage.get_gtt(created.id)

        assert retrieved.id == created.id
        assert retrieved.symbol == created.symbol
        assert retrieved.trigger_price == created.trigger_price

    @pytest.mark.asyncio
    async def test_get_nonexistent_gtt(self, storage):
        """Test retrieving non-existent GTT raises error."""
        with pytest.raises(GTTNotFoundError):
            await storage.get_gtt(99999)

    @pytest.mark.asyncio
    async def test_get_active_gtts(self, storage):
        """Test retrieving all active GTTs."""
        # Create multiple GTTs
        await storage.create_gtt(
            symbol="RELIANCE",
            exchange="NSE",
            trigger_price=2500.0,
            order_type="LIMIT",
            action="BUY",
            quantity=1,
            limit_price=2490.0
        )

        await storage.create_gtt(
            symbol="TCS",
            exchange="NSE",
            trigger_price=3500.0,
            order_type="LIMIT",
            action="SELL",
            quantity=1,
            limit_price=3510.0
        )

        active = await storage.get_active_gtts()

        assert len(active) == 2
        assert all(gtt.status == GTTStatus.ACTIVE.value for gtt in active)

    @pytest.mark.asyncio
    async def test_get_gtts_by_symbol(self, storage):
        """Test retrieving GTTs by symbol."""
        # Create GTTs for different symbols
        await storage.create_gtt(
            symbol="RELIANCE",
            exchange="NSE",
            trigger_price=2500.0,
            order_type="LIMIT",
            action="BUY",
            quantity=1,
            limit_price=2490.0
        )

        await storage.create_gtt(
            symbol="RELIANCE",
            exchange="NSE",
            trigger_price=2600.0,
            order_type="LIMIT",
            action="SELL",
            quantity=1,
            limit_price=2610.0
        )

        await storage.create_gtt(
            symbol="TCS",
            exchange="NSE",
            trigger_price=3500.0,
            order_type="LIMIT",
            action="BUY",
            quantity=1,
            limit_price=3490.0
        )

        reliance_gtts = await storage.get_gtts_by_symbol("RELIANCE", "NSE")

        assert len(reliance_gtts) == 2
        assert all(gtt.symbol == "RELIANCE" for gtt in reliance_gtts)


class TestGTTStatusUpdate:
    """Test GTT status updates."""

    @pytest.mark.asyncio
    async def test_update_to_triggered(self, storage):
        """Test updating GTT to TRIGGERED status."""
        gtt = await storage.create_gtt(
            symbol="RELIANCE",
            exchange="NSE",
            trigger_price=2500.0,
            order_type="LIMIT",
            action="BUY",
            quantity=1,
            limit_price=2490.0
        )

        updated = await storage.update_gtt_status(
            gtt.id,
            GTTStatus.TRIGGERED.value,
            order_id="ORDER123",
            trigger_ltp=2499.0
        )

        assert updated.status == GTTStatus.TRIGGERED.value
        assert updated.order_id == "ORDER123"
        assert updated.triggered_at is not None

    @pytest.mark.asyncio
    async def test_update_to_failed(self, storage):
        """Test updating GTT to FAILED status."""
        gtt = await storage.create_gtt(
            symbol="RELIANCE",
            exchange="NSE",
            trigger_price=2500.0,
            order_type="LIMIT",
            action="BUY",
            quantity=1,
            limit_price=2490.0
        )

        updated = await storage.update_gtt_status(
            gtt.id,
            GTTStatus.FAILED.value,
            error_message="Risk validation failed"
        )

        assert updated.status == GTTStatus.FAILED.value
        assert updated.error_message == "Risk validation failed"
        assert updated.completed_at is not None

    @pytest.mark.asyncio
    async def test_update_nonexistent_gtt(self, storage):
        """Test updating non-existent GTT raises error."""
        with pytest.raises(GTTNotFoundError):
            await storage.update_gtt_status(99999, GTTStatus.CANCELLED.value)


class TestGTTCancellation:
    """Test GTT cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_active_gtt(self, storage):
        """Test cancelling active GTT."""
        gtt = await storage.create_gtt(
            symbol="RELIANCE",
            exchange="NSE",
            trigger_price=2500.0,
            order_type="LIMIT",
            action="BUY",
            quantity=1,
            limit_price=2490.0
        )

        cancelled = await storage.cancel_gtt(gtt.id)

        assert cancelled.status == GTTStatus.CANCELLED.value
        assert cancelled.completed_at is not None

    @pytest.mark.asyncio
    async def test_cancel_triggered_gtt_fails(self, storage):
        """Test cancelling triggered GTT fails."""
        gtt = await storage.create_gtt(
            symbol="RELIANCE",
            exchange="NSE",
            trigger_price=2500.0,
            order_type="LIMIT",
            action="BUY",
            quantity=1,
            limit_price=2490.0
        )

        # Update to TRIGGERED
        await storage.update_gtt_status(gtt.id, GTTStatus.TRIGGERED.value)

        # Try to cancel
        with pytest.raises(GTTError) as exc_info:
            await storage.cancel_gtt(gtt.id)

        assert "cannot cancel" in str(exc_info.value).lower()


class TestGTTDeletion:
    """Test GTT deletion."""

    @pytest.mark.asyncio
    async def test_delete_gtt(self, storage):
        """Test deleting GTT."""
        gtt = await storage.create_gtt(
            symbol="RELIANCE",
            exchange="NSE",
            trigger_price=2500.0,
            order_type="LIMIT",
            action="BUY",
            quantity=1,
            limit_price=2490.0
        )

        result = await storage.delete_gtt(gtt.id)

        assert result is True

        # Verify it's gone
        with pytest.raises(GTTNotFoundError):
            await storage.get_gtt(gtt.id)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_gtt(self, storage):
        """Test deleting non-existent GTT raises error."""
        with pytest.raises(GTTNotFoundError):
            await storage.delete_gtt(99999)


class TestStatistics:
    """Test statistics."""

    @pytest.mark.asyncio
    async def test_get_statistics(self, storage):
        """Test getting statistics."""
        # Create various GTTs
        gtt1 = await storage.create_gtt(
            symbol="RELIANCE",
            exchange="NSE",
            trigger_price=2500.0,
            order_type="LIMIT",
            action="BUY",
            quantity=1,
            limit_price=2490.0
        )

        gtt2 = await storage.create_gtt(
            symbol="TCS",
            exchange="NSE",
            trigger_price=3500.0,
            order_type="LIMIT",
            action="SELL",
            quantity=1,
            limit_price=3510.0
        )

        # Update statuses
        await storage.update_gtt_status(gtt1.id, GTTStatus.TRIGGERED.value)
        await storage.cancel_gtt(gtt2.id)

        stats = await storage.get_statistics()

        assert stats['total'] == 2
        assert stats['active'] == 0
        assert stats['triggered'] == 1
        assert stats['cancelled'] == 1
