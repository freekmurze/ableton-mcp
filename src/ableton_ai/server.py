"""MCP server entry point.

This file used to be 2,828 lines holding all 128 tools inline. The tools now
live in ``ableton_ai.tools``, grouped by what they touch, and this is just the
wiring.
"""

from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

from .config import settings
from .tools import register_all

logger = logging.getLogger(__name__)

#: Every tool defined across the tool modules. If a module fails to import, the
#: count drops and startup fails loudly rather than quietly serving a subset.
EXPECTED_TOOL_COUNT = 148


def create_server() -> FastMCP:
    """Build the MCP server with every tool registered."""
    mcp = FastMCP(
        "AbletonMCP",
        instructions=(
            "Control Ableton Live. You cannot hear anything you make, so never "
            "claim something sounds good. Read parameters back after setting them; "
            "a success status does not prove a change landed. Anything that is a "
            "dropdown in Live (LFO Map, sidechain source, Drift's mod matrix) "
            "cannot be set through this API. Ask the user to click those."
        ),
    )
    count = register_all(mcp)
    logger.info("registered %d tools", count)

    if count != EXPECTED_TOOL_COUNT:
        logger.warning(
            "expected %d tools but registered %d; a tool module may have failed to import",
            EXPECTED_TOOL_COUNT,
            count,
        )
    return mcp


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,  # stdout is the MCP transport; logging there corrupts it
    )
    logger.info("connecting to Ableton at %s:%s", settings.host, settings.port)
    create_server().run()


if __name__ == "__main__":
    main()
