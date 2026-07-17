"""Shared plumbing for tool modules.

Every tool in the original ``server.py`` repeated the same five lines:

    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("x", {...})
        return f"..."
    except Exception as e:
        logger.error(f"Error ...: {str(e)}")
        return f"Error ...: {str(e)}"

128 times over, which is roughly 640 lines that say nothing. The decorator below
does it once.
"""

from __future__ import annotations

import functools
import json
import logging
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from ..connection import AbletonConnection, get_ableton_connection
from ..exceptions import AbletonMCPError

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

#: Populated by @tool. Each module's tools land here in definition order, and
#: register_all() walks it. Modules therefore need no registration boilerplate.
REGISTRY: list[Callable[..., Any]] = []


def connection() -> AbletonConnection:
    """The shared connection to Live."""
    return get_ableton_connection()


def tool(fn: Callable[P, R]) -> Callable[P, R]:
    """Mark a function as an MCP tool and give it uniform error handling.

    MCP tools return strings that a model reads, so an exception has to become
    readable text rather than a traceback. But the message needs to be useful:
    our own exceptions already explain what to do (ConnectionFailedError names
    the Control Surface setting), so they are surfaced as-is. Anything else is
    unexpected and gets logged with a traceback.
    """

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
        try:
            return fn(*args, **kwargs)
        except AbletonMCPError as exc:
            # Expected and already actionable. No traceback needed.
            logger.info("%s: %s", fn.__name__, exc)
            return f"Error: {exc}"
        except Exception as exc:
            logger.exception("unexpected error in %s", fn.__name__)
            return f"Error in {fn.__name__}: {exc}"

    REGISTRY.append(wrapper)
    return wrapper


def as_json(data: Any) -> str:
    """Render a result as JSON for the model to read."""
    return json.dumps(data, indent=2, default=str)
