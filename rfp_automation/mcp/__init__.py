"""
MCP — the single boundary agents interact with.

Agents import ONLY from this package:
    from rfp_automation.mcp import MCPService

They never touch internal modules (embedding, vector DB).
"""

from .mcp_server import MCPService

__all__ = ["MCPService"]
