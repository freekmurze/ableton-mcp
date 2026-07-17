"""Tool modules, grouped by what they touch.

``server.py`` used to be one 2,800 line file holding all 128 tools. Splitting by
domain means you can find the clip tools without scrolling past the warp markers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import (
    arrangement,
    automation,
    browser,
    clips,
    devices,
    music,
    notes,
    session,
    tracks,
)
from ._base import REGISTRY, as_json, connection, tool

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

MODULES = (
    session,
    tracks,
    clips,
    notes,
    devices,
    browser,
    automation,
    arrangement,
    music,
)


def register_all(mcp: FastMCP) -> int:
    """Register every tool with the MCP server. Returns how many were registered.

    The count is returned so startup can assert it, rather than silently serving
    a partial toolset if a module fails to import.
    """
    for fn in REGISTRY:
        mcp.tool()(fn)
    return len(REGISTRY)


__all__ = [
    "MODULES",
    "REGISTRY",
    "as_json",
    "connection",
    "register_all",
    "tool",
]
