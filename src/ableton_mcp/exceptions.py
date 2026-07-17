"""Exception hierarchy.

The original code raised bare ``Exception`` and ``ConnectionError``, so callers
could not tell "Ableton is not running" apart from "that command does not
exist" apart from "Live took too long". Each of those wants a different
response, so each gets its own type.
"""

from __future__ import annotations


class AbletonMCPError(Exception):
    """Base for every error this package raises."""


class ConnectionFailedError(AbletonMCPError):
    """Could not reach the remote script.

    Almost always one of: Live is not running, the Control Surface is not set
    to AbletonMCP, or something else already holds the port.
    """

    def __init__(self, host: str, port: int, reason: str | None = None) -> None:
        self.host = host
        self.port = port
        self.reason = reason
        detail = f": {reason}" if reason else ""
        super().__init__(
            f"Could not connect to Ableton at {host}:{port}{detail}. "
            f"Check that Live is running and that AbletonMCP is selected under "
            f"Settings > Link, Tempo & MIDI > Control Surface."
        )


class NotConnectedError(AbletonMCPError):
    """A command was issued before a connection existed."""


class CommandTimeoutError(AbletonMCPError):
    """Live did not answer in time.

    A modifying command has to be marshalled onto Live's main thread, so it can
    legitimately be slow when Live is busy. A timeout is not proof of failure:
    the command may still have run.
    """

    def __init__(self, command_type: str, timeout: float) -> None:
        self.command_type = command_type
        self.timeout = timeout
        super().__init__(
            f"'{command_type}' did not respond within {timeout}s. "
            f"It may still have been applied; read the state back to check."
        )


class CommandFailedError(AbletonMCPError):
    """The remote script ran the command and reported an error."""

    def __init__(self, command_type: str, message: str) -> None:
        self.command_type = command_type
        self.message = message
        super().__init__(f"'{command_type}' failed: {message}")


class InvalidResponseError(AbletonMCPError):
    """The remote script sent something that was not valid JSON."""
