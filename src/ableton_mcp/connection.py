"""Socket client for the AbletonMCP remote script.

This class previously existed twice, once in ``server.py`` and once in
``rest_api_server.py``. The copies drifted: the MCP one grew chunked-response
handling, the REST one grew reconnect-on-failure, and neither had the other's
fix. This is the merge of both, and the only copy.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from types import TracebackType
from typing import Any

from .config import Settings, settings
from .exceptions import (
    CommandFailedError,
    CommandTimeoutError,
    ConnectionFailedError,
    InvalidResponseError,
    NotConnectedError,
)

logger = logging.getLogger(__name__)


class AbletonConnection:
    """Thread-safe client for the remote script's JSON-over-TCP socket.

    The socket accepts one command at a time, so every exchange is serialised
    behind a lock. Without it, concurrent callers interleave their bytes and
    both responses become unparseable.
    """

    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or settings
        self.host = self.config.host
        self.port = self.config.port
        self._sock: socket.socket | None = None
        self._lock = threading.RLock()

    # -- lifecycle ---------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> bool:
        """Connect, retrying a few times. Returns True once connected."""
        with self._lock:
            if self._sock is not None:
                return True

            last: Exception | None = None
            for attempt in range(1, self.config.max_connect_attempts + 1):
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(self.config.recv_timeout)
                    sock.connect((self.host, self.port))
                except OSError as exc:
                    last = exc
                    logger.debug(
                        "connect attempt %d/%d failed: %s",
                        attempt,
                        self.config.max_connect_attempts,
                        exc,
                    )
                    if attempt < self.config.max_connect_attempts:
                        time.sleep(self.config.retry_delay)
                else:
                    self._sock = sock
                    logger.info("connected to Ableton at %s:%s", self.host, self.port)
                    return True

            raise ConnectionFailedError(self.host, self.port, str(last) if last else None)

    def disconnect(self) -> None:
        with self._lock:
            if self._sock is None:
                return
            try:
                self._sock.close()
            except OSError:
                logger.debug("error while closing socket", exc_info=True)
            finally:
                self._sock = None

    def reconnect(self) -> bool:
        """Drop the socket and dial again. Used after a failed exchange."""
        with self._lock:
            self.disconnect()
            return self.connect()

    # -- io ----------------------------------------------------------------

    def _receive_full_response(self, sock: socket.socket) -> dict[str, Any]:
        """Read until the buffer parses as JSON.

        TCP does not preserve message boundaries, so a single response can
        arrive across several recv() calls. Parsing the first chunk on its own
        fails on any response larger than the buffer, which is most of the
        interesting ones (a full browser tree, say).
        """
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(self.config.buffer_size)
            if not chunk:
                if not chunks:
                    raise InvalidResponseError("Connection closed without a response")
                break
            chunks.append(chunk)
            try:
                return json.loads(b"".join(chunks).decode("utf-8"))  # type: ignore[no-any-return]
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue  # partial message, keep reading

        try:
            return json.loads(b"".join(chunks).decode("utf-8"))  # type: ignore[no-any-return]
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise InvalidResponseError(f"Malformed response from Ableton: {exc}") from exc

    def send_command(
        self,
        command_type: str,
        params: dict[str, Any] | None = None,
        *,
        retry: bool = True,
    ) -> dict[str, Any]:
        """Send one command and return its ``result``.

        Raises CommandFailedError if the remote script reports an error, rather
        than returning it. A caller that has to inspect a status field to notice
        failure will eventually forget to.
        """
        with self._lock:
            if self._sock is None and not self.connect():
                raise NotConnectedError("Not connected to Ableton")

            sock = self._sock
            if sock is None:  # pragma: no cover - connect() raises instead
                raise NotConnectedError("Not connected to Ableton")

            timeout = self.config.timeout_for(command_type)
            sock.settimeout(timeout)
            payload = json.dumps({"type": command_type, "params": params or {}}).encode("utf-8")

            try:
                sock.sendall(payload)
                response = self._receive_full_response(sock)
            except TimeoutError as exc:
                self.disconnect()
                raise CommandTimeoutError(command_type, timeout) from exc
            except (OSError, InvalidResponseError):
                self.disconnect()
                if retry:
                    logger.warning("'%s' failed, reconnecting and retrying once", command_type)
                    self.reconnect()
                    return self.send_command(command_type, params, retry=False)
                raise

            if response.get("status") == "error":
                raise CommandFailedError(command_type, response.get("message", "unknown error"))

            # Give Live a beat to settle before the next command.
            if self.config.command_delay:
                time.sleep(self.config.command_delay)

            result = response.get("result", {})
            return result if isinstance(result, dict) else {"value": result}

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> AbletonConnection:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.disconnect()


_connection: AbletonConnection | None = None
_connection_lock = threading.Lock()


def get_ableton_connection() -> AbletonConnection:
    """Return the shared connection, opening it on first use."""
    global _connection
    with _connection_lock:
        if _connection is None:
            _connection = AbletonConnection()
            _connection.connect()
        return _connection


def reset_connection() -> None:
    """Drop the shared connection. Mostly here so tests can isolate."""
    global _connection
    with _connection_lock:
        if _connection is not None:
            _connection.disconnect()
        _connection = None
