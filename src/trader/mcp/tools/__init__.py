"""
MCP Tools Package.

This package contains all MCP tools for the automated trading system.
Importing this module registers all tools with the MCP server.
"""

# Import all tool modules to register them with the MCP server
from . import market_data  # noqa: F401
from . import orders  # noqa: F401
from . import portfolio  # noqa: F401
from . import gtt  # noqa: F401

__all__ = [
    "market_data",
    "orders",
    "portfolio",
    "gtt"
]
