"""
MCP Tools for Market Data Operations.

Provides tools for fetching real-time and historical market data from Groww API.
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from mcp.server.fastmcp import Context

from ..server import mcp
from ...core.logging_config import get_logger

logger = get_logger(__name__)


@mcp.tool()
async def get_quote(
    symbol: str,
    exchange: str = "NSE",
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Get real-time quote for a symbol.

    Args:
        symbol: Stock symbol (e.g., "RELIANCE", "TCS")
        exchange: Exchange name (NSE or BSE), defaults to NSE

    Returns:
        Quote data including LTP, bid, ask, volume, OHLC, etc.

    Example:
        get_quote(symbol="RELIANCE", exchange="NSE")
    """
    logger.info(f"Fetching quote for {symbol} on {exchange}")

    try:
        groww_client = ctx.request_context.groww_client
        quote = await groww_client.get_quote(symbol, exchange)

        logger.info(
            "Quote fetched successfully",
            symbol=symbol,
            exchange=exchange,
            ltp=quote.ltp
        )

        return quote.model_dump()

    except Exception as e:
        logger.error(f"Error fetching quote: {e}", symbol=symbol, exchange=exchange)
        raise


@mcp.tool()
async def get_ltp(
    symbol: str,
    exchange: str = "NSE",
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Get Last Traded Price (LTP) for a symbol.

    Args:
        symbol: Stock symbol (e.g., "RELIANCE", "TCS")
        exchange: Exchange name (NSE or BSE), defaults to NSE

    Returns:
        Dictionary with symbol, exchange, and LTP

    Example:
        get_ltp(symbol="TCS", exchange="NSE")
    """
    logger.info(f"Fetching LTP for {symbol} on {exchange}")

    try:
        groww_client = ctx.request_context.groww_client
        ltp = await groww_client.get_ltp(symbol, exchange)

        logger.info(
            "LTP fetched successfully",
            symbol=symbol,
            exchange=exchange,
            ltp=ltp
        )

        return {
            "symbol": symbol,
            "exchange": exchange,
            "ltp": ltp,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error fetching LTP: {e}", symbol=symbol, exchange=exchange)
        raise


@mcp.tool()
async def get_ohlc(
    symbol: str,
    exchange: str = "NSE",
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Get OHLC (Open, High, Low, Close) data for a symbol.

    Args:
        symbol: Stock symbol (e.g., "RELIANCE", "TCS")
        exchange: Exchange name (NSE or BSE), defaults to NSE

    Returns:
        OHLC data for the current trading day

    Example:
        get_ohlc(symbol="INFY", exchange="NSE")
    """
    logger.info(f"Fetching OHLC for {symbol} on {exchange}")

    try:
        groww_client = ctx.request_context.groww_client
        ohlc = await groww_client.get_ohlc(symbol, exchange)

        logger.info(
            "OHLC fetched successfully",
            symbol=symbol,
            exchange=exchange,
            open=ohlc.open,
            high=ohlc.high,
            low=ohlc.low,
            close=ohlc.close
        )

        return ohlc.model_dump()

    except Exception as e:
        logger.error(f"Error fetching OHLC: {e}", symbol=symbol, exchange=exchange)
        raise


@mcp.tool()
async def get_historical_data(
    symbol: str,
    exchange: str = "NSE",
    days_back: int = 30,
    interval: str = "1d",
    ctx: Optional[Context] = None
) -> List[Dict[str, Any]]:
    """
    Get historical OHLCV data for a symbol.

    Args:
        symbol: Stock symbol (e.g., "RELIANCE", "TCS")
        exchange: Exchange name (NSE or BSE), defaults to NSE
        days_back: Number of days of historical data to fetch (default: 30)
        interval: Data interval - "1d" (daily), "1h" (hourly), "5m" (5-min), etc.

    Returns:
        List of OHLCV candles with timestamp, open, high, low, close, volume

    Example:
        get_historical_data(symbol="RELIANCE", exchange="NSE", days_back=90, interval="1d")
    """
    logger.info(
        f"Fetching {days_back} days of historical data for {symbol} on {exchange}",
        interval=interval
    )

    try:
        groww_client = ctx.request_context.groww_client

        # Calculate date range
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days_back)

        # Fetch historical data
        candles = await groww_client.get_historical_data(
            symbol=symbol,
            exchange=exchange,
            from_date=from_date,
            to_date=to_date,
            interval=interval
        )

        logger.info(
            "Historical data fetched successfully",
            symbol=symbol,
            exchange=exchange,
            candles_count=len(candles)
        )

        return [candle.model_dump() for candle in candles]

    except Exception as e:
        logger.error(
            f"Error fetching historical data: {e}",
            symbol=symbol,
            exchange=exchange,
            days_back=days_back
        )
        raise


@mcp.tool()
async def get_multiple_ltps(
    symbols: List[str],
    exchange: str = "NSE",
    ctx: Optional[Context] = None
) -> Dict[str, float]:
    """
    Get Last Traded Prices for multiple symbols at once.

    Args:
        symbols: List of stock symbols (e.g., ["RELIANCE", "TCS", "INFY"])
        exchange: Exchange name (NSE or BSE), defaults to NSE

    Returns:
        Dictionary mapping symbols to their LTPs

    Example:
        get_multiple_ltps(symbols=["RELIANCE", "TCS", "INFY"], exchange="NSE")
    """
    logger.info(f"Fetching LTPs for {len(symbols)} symbols on {exchange}")

    try:
        groww_client = ctx.request_context.groww_client
        results = {}

        for symbol in symbols:
            try:
                ltp = await groww_client.get_ltp(symbol, exchange)
                results[symbol] = ltp
            except Exception as e:
                logger.warning(f"Failed to fetch LTP for {symbol}: {e}")
                results[symbol] = None

        logger.info(
            "Multiple LTPs fetched",
            total_symbols=len(symbols),
            successful=sum(1 for v in results.values() if v is not None)
        )

        return results

    except Exception as e:
        logger.error(f"Error fetching multiple LTPs: {e}", symbols=symbols)
        raise


@mcp.tool()
async def get_market_status(
    ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """
    Get current market status (open/closed) and trading hours.

    Returns:
        Market status information including:
        - is_market_open: Boolean indicating if market is currently open
        - current_time: Current timestamp
        - market_type: "pre_market", "regular", "post_market", or "closed"

    Example:
        get_market_status()
    """
    logger.info("Fetching market status")

    try:
        now = datetime.now()
        current_time = now.time()

        # NSE trading hours (IST)
        pre_market_start = datetime.strptime("09:00", "%H:%M").time()
        regular_market_start = datetime.strptime("09:15", "%H:%M").time()
        regular_market_end = datetime.strptime("15:30", "%H:%M").time()
        post_market_end = datetime.strptime("16:00", "%H:%M").time()

        # Determine market status
        is_weekend = now.weekday() >= 5  # Saturday = 5, Sunday = 6

        if is_weekend:
            market_type = "closed"
            is_market_open = False
        elif pre_market_start <= current_time < regular_market_start:
            market_type = "pre_market"
            is_market_open = False
        elif regular_market_start <= current_time < regular_market_end:
            market_type = "regular"
            is_market_open = True
        elif regular_market_end <= current_time < post_market_end:
            market_type = "post_market"
            is_market_open = False
        else:
            market_type = "closed"
            is_market_open = False

        status = {
            "is_market_open": is_market_open,
            "market_type": market_type,
            "current_time": now.isoformat(),
            "trading_hours": {
                "pre_market": "09:00 - 09:15 IST",
                "regular_market": "09:15 - 15:30 IST",
                "post_market": "15:30 - 16:00 IST"
            }
        }

        logger.info(
            "Market status fetched",
            is_open=is_market_open,
            market_type=market_type
        )

        return status

    except Exception as e:
        logger.error(f"Error fetching market status: {e}")
        raise
