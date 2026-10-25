"""AltFinance MCP Server — luxury asset auction data for Claude.

Connects Claude Desktop and Claude Code to the AltFinance API,
giving Claude direct access to query watches, handbags, and jewelry
auction data in conversation.
"""

__version__ = "0.4.5"

from altfinance_mcp.server import main

__all__ = ["main"]
