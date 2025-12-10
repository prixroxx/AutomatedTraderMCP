"""
Logging configuration with structured logging support.

This module sets up comprehensive logging with:
- JSON structured logging for machine parsing
- Rich console output for human readability
- Daily log rotation
- Different log levels for different modules
"""

import logging
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime
import structlog
from structlog.types import FilteringBoundLogger
from pythonjsonlogger import jsonlogger


# Global logger cache
_loggers: dict[str, FilteringBoundLogger] = {}


def setup_logging(
    log_level: str = "INFO",
    log_format: str = "json",
    console_output: bool = True,
    file_output: bool = True,
    log_dir: Optional[Path] = None
) -> None:
    """
    Setup structured logging for the entire application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Format type ("json" or "text")
        console_output: Enable console logging
        file_output: Enable file logging
        log_dir: Directory for log files
    """
    # Get log directory
    if log_dir is None:
        from .config import get_config
        config = get_config()
        log_dir = config.get_log_dir()

    # Create log directory if it doesn't exist
    log_dir.mkdir(parents=True, exist_ok=True)

    # Convert log level string to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        level=numeric_level,
        handlers=[]
    )

    # Handlers list
    handlers = []

    # Console handler with Rich formatting (if enabled)
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)

        if log_format == "json":
            # JSON formatter for console
            json_formatter = jsonlogger.JsonFormatter(
                fmt='%(asctime)s %(name)s %(levelname)s %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            console_handler.setFormatter(json_formatter)
        else:
            # Text formatter for console
            console_formatter = logging.Formatter(
                fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            console_handler.setFormatter(console_formatter)

        handlers.append(console_handler)

    # File handler with daily rotation (if enabled)
    if file_output:
        # Create log filename with date
        today = datetime.now().strftime('%Y-%m-%d')
        log_file = log_dir / f"trader_{today}.log"

        file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
        file_handler.setLevel(numeric_level)

        # Always use JSON for file logging
        json_formatter = jsonlogger.JsonFormatter(
            fmt='%(asctime)s %(name)s %(levelname)s %(message)s %(pathname)s %(lineno)d',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(json_formatter)
        handlers.append(file_handler)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers = []
    for handler in handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(numeric_level)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Log startup message
    logger = get_logger("trader.core.logging")
    logger.info(
        "Logging initialized",
        level=log_level,
        format=log_format,
        console=console_output,
        file=file_output,
        log_dir=str(log_dir) if log_dir else None
    )


def get_logger(name: str) -> FilteringBoundLogger:
    """
    Get a logger instance for the given name.

    Args:
        name: Logger name (usually __name__)

    Returns:
        FilteringBoundLogger: Structured logger instance

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Operation completed", order_id="12345", status="success")
    """
    if name not in _loggers:
        _loggers[name] = structlog.get_logger(name)

    return _loggers[name]


def log_function_call(logger: FilteringBoundLogger):
    """
    Decorator to log function calls with parameters and results.

    Args:
        logger: Logger instance to use

    Example:
        >>> @log_function_call(logger)
        >>> def place_order(symbol, quantity):
        >>>     return f"Order placed for {symbol}"
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger.debug(
                f"Calling {func.__name__}",
                function=func.__name__,
                args=args,
                kwargs=kwargs
            )

            try:
                result = func(*args, **kwargs)
                logger.debug(
                    f"Completed {func.__name__}",
                    function=func.__name__},
                    success=True
                )
                return result
            except Exception as e:
                logger.error(
                    f"Error in {func.__name__}",
                    function=func.__name__,
                    error=str(e),
                    exception_type=type(e).__name__
                )
                raise

        return wrapper
    return decorator


def log_api_call(
    logger: FilteringBoundLogger,
    api_name: str,
    endpoint: str,
    method: str = "GET"
):
    """
    Decorator to log API calls.

    Args:
        logger: Logger instance
        api_name: Name of the API (e.g., "groww")
        endpoint: API endpoint
        method: HTTP method

    Example:
        >>> @log_api_call(logger, "groww", "/orders", "POST")
        >>> def place_order(order_data):
        >>>     return api_client.post("/orders", order_data)
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger.info(
                f"API call: {api_name}",
                api=api_name,
                endpoint=endpoint,
                method=method,
                function=func.__name__
            )

            start_time = datetime.now()

            try:
                result = func(*args, **kwargs)

                duration = (datetime.now() - start_time).total_seconds()
                logger.info(
                    f"API call successful: {api_name}",
                    api=api_name,
                    endpoint=endpoint,
                    method=method,
                    duration_seconds=duration,
                    success=True
                )

                return result

            except Exception as e:
                duration = (datetime.now() - start_time).total_seconds()
                logger.error(
                    f"API call failed: {api_name}",
                    api=api_name,
                    endpoint=endpoint,
                    method=method,
                    duration_seconds=duration,
                    error=str(e),
                    exception_type=type(e).__name__,
                    success=False
                )
                raise

        return wrapper
    return decorator


def log_order_event(
    logger: FilteringBoundLogger,
    event_type: str,
    symbol: str,
    **kwargs
):
    """
    Log order-related events with standardized format.

    Args:
        logger: Logger instance
        event_type: Type of event (e.g., "order_placed", "order_rejected")
        symbol: Stock symbol
        **kwargs: Additional context fields

    Example:
        >>> log_order_event(
        ...     logger, "order_placed",
        ...     symbol="RELIANCE",
        ...     order_id="12345",
        ...     quantity=10,
        ...     price=2500
        ... )
    """
    logger.info(
        f"Order event: {event_type}",
        event_type=event_type,
        symbol=symbol,
        timestamp=datetime.now().isoformat(),
        **kwargs
    )


def log_risk_event(
    logger: FilteringBoundLogger,
    event_type: str,
    severity: str,
    **kwargs
):
    """
    Log risk management events with standardized format.

    Args:
        logger: Logger instance
        event_type: Type of risk event (e.g., "limit_exceeded", "kill_switch_activated")
        severity: Severity level ("low", "medium", "high", "critical")
        **kwargs: Additional context fields

    Example:
        >>> log_risk_event(
        ...     logger, "daily_loss_limit_exceeded",
        ...     severity="critical",
        ...     daily_loss=2500,
        ...     limit=2000
        ... )
    """
    # Map severity to log level
    level_map = {
        'low': logger.info,
        'medium': logger.warning,
        'high': logger.error,
        'critical': logger.critical
    }

    log_func = level_map.get(severity, logger.warning)

    log_func(
        f"Risk event: {event_type}",
        event_type=event_type,
        severity=severity,
        timestamp=datetime.now().isoformat(),
        **kwargs
    )


def cleanup_old_logs(log_dir: Path, retention_days: int = 90):
    """
    Clean up log files older than retention period.

    Args:
        log_dir: Directory containing log files
        retention_days: Number of days to retain logs

    Example:
        >>> cleanup_old_logs(Path("data/logs"), retention_days=90)
    """
    if not log_dir.exists():
        return

    from datetime import timedelta

    cutoff_date = datetime.now() - timedelta(days=retention_days)
    logger = get_logger("trader.core.logging")

    deleted_count = 0

    for log_file in log_dir.glob("trader_*.log"):
        try:
            # Extract date from filename (trader_YYYY-MM-DD.log)
            date_str = log_file.stem.split('_')[1]
            file_date = datetime.strptime(date_str, '%Y-%m-%d')

            if file_date < cutoff_date:
                log_file.unlink()
                deleted_count += 1
                logger.debug(
                    "Deleted old log file",
                    file=str(log_file),
                    file_date=date_str
                )

        except (ValueError, IndexError) as e:
            logger.warning(
                "Could not parse log file date",
                file=str(log_file),
                error=str(e)
            )

    if deleted_count > 0:
        logger.info(
            "Cleaned up old log files",
            deleted_count=deleted_count,
            retention_days=retention_days
        )


# Initialize logging on module import
def _init_logging():
    """Initialize logging when module is imported."""
    try:
        from .config import get_config
        config = get_config()

        setup_logging(
            log_level=config.get('logging.level', 'INFO'),
            log_format=config.get('logging.format', 'json'),
            console_output=config.get('logging.console', True),
            file_output=config.get('logging.file', True),
            log_dir=config.get_log_dir()
        )

        # Schedule log cleanup
        retention_days = config.get('logging.retention_days', 90)
        cleanup_old_logs(config.get_log_dir(), retention_days)

    except Exception as e:
        # Fallback to basic logging if config fails
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
        )
        logging.error(f"Failed to initialize structured logging: {e}")


# Auto-initialize when imported
try:
    _init_logging()
except Exception:
    # Silently fail if config not ready yet
    pass
