"""Tests for the socket client.

These cover the bugs the two duplicated copies each had, so the merged version
cannot regress either of them.
"""

from __future__ import annotations

import json
import socket
from typing import Any

import pytest

from ableton_mcp.config import Settings
from ableton_mcp.connection import AbletonConnection
from ableton_mcp.exceptions import (
    CommandFailedError,
    CommandTimeoutError,
    ConnectionFailedError,
    InvalidResponseError,
)


class FakeSocket:
    """Stand-in for a real socket, so tests never touch the network."""

    def __init__(
        self, chunks: list[bytes] | None = None, *, raise_on_connect: Exception | None = None
    ):
        self._chunks = list(chunks or [])
        self.sent: list[bytes] = []
        self.closed = False
        self.timeouts: list[float] = []
        self._raise_on_connect = raise_on_connect

    def settimeout(self, t: float) -> None:
        self.timeouts.append(t)

    def connect(self, addr: tuple[str, int]) -> None:
        if self._raise_on_connect is not None:
            raise self._raise_on_connect

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, _n: int) -> bytes:
        if not self._chunks:
            return b""
        chunk = self._chunks.pop(0)
        if isinstance(chunk, Exception):
            raise chunk
        return chunk

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fast_settings() -> Settings:
    """No sleeping in tests."""
    return Settings(retry_delay=0.0, command_delay=0.0, max_connect_attempts=2)


def _patch_socket(monkeypatch: pytest.MonkeyPatch, sock: Any) -> None:
    monkeypatch.setattr(socket, "socket", lambda *a, **k: sock)


def test_connect_succeeds(monkeypatch: pytest.MonkeyPatch, fast_settings: Settings) -> None:
    _patch_socket(monkeypatch, FakeSocket())
    conn = AbletonConnection(fast_settings)

    assert conn.connect() is True
    assert conn.connected


def test_connect_raises_with_actionable_message(
    monkeypatch: pytest.MonkeyPatch, fast_settings: Settings
) -> None:
    _patch_socket(monkeypatch, FakeSocket(raise_on_connect=ConnectionRefusedError("nope")))
    conn = AbletonConnection(fast_settings)

    with pytest.raises(ConnectionFailedError) as exc:
        conn.connect()

    # The message has to tell a musician what to actually do.
    assert "Control Surface" in str(exc.value)
    assert "9877" in str(exc.value)


def test_connect_retries_before_giving_up(
    monkeypatch: pytest.MonkeyPatch, fast_settings: Settings
) -> None:
    attempts = []

    def make_sock(*_a: Any, **_k: Any) -> FakeSocket:
        attempts.append(1)
        return FakeSocket(raise_on_connect=ConnectionRefusedError("nope"))

    monkeypatch.setattr(socket, "socket", make_sock)
    with pytest.raises(ConnectionFailedError):
        AbletonConnection(fast_settings).connect()

    assert len(attempts) == fast_settings.max_connect_attempts


def test_send_command_returns_result(
    monkeypatch: pytest.MonkeyPatch, fast_settings: Settings
) -> None:
    payload = json.dumps({"status": "success", "result": {"tempo": 129.0}}).encode()
    _patch_socket(monkeypatch, FakeSocket([payload]))
    conn = AbletonConnection(fast_settings)

    assert conn.send_command("get_session_info") == {"tempo": 129.0}


def test_send_command_serialises_the_request(
    monkeypatch: pytest.MonkeyPatch, fast_settings: Settings
) -> None:
    sock = FakeSocket([json.dumps({"status": "success", "result": {}}).encode()])
    _patch_socket(monkeypatch, sock)
    conn = AbletonConnection(fast_settings)

    conn.send_command("set_tempo", {"tempo": 129.0})

    assert json.loads(sock.sent[0]) == {"type": "set_tempo", "params": {"tempo": 129.0}}


def test_response_split_across_chunks_is_reassembled(
    monkeypatch: pytest.MonkeyPatch, fast_settings: Settings
) -> None:
    """The REST copy of this class lacked chunked reads and broke on big responses."""
    full = json.dumps({"status": "success", "result": {"items": list(range(500))}}).encode()
    mid = len(full) // 2
    _patch_socket(monkeypatch, FakeSocket([full[:mid], full[mid:]]))
    conn = AbletonConnection(fast_settings)

    result = conn.send_command("get_browser_tree")

    assert result["items"] == list(range(500))


def test_error_status_raises_rather_than_returning(
    monkeypatch: pytest.MonkeyPatch, fast_settings: Settings
) -> None:
    """A status field callers must remember to check is a status field they will forget."""
    payload = json.dumps({"status": "error", "message": "Unknown command: nope"}).encode()
    _patch_socket(monkeypatch, FakeSocket([payload]))
    conn = AbletonConnection(fast_settings)

    with pytest.raises(CommandFailedError) as exc:
        conn.send_command("nope")

    assert "Unknown command" in str(exc.value)


def test_timeout_says_the_command_may_still_have_applied(
    monkeypatch: pytest.MonkeyPatch, fast_settings: Settings
) -> None:
    _patch_socket(monkeypatch, FakeSocket([TimeoutError("timed out")]))  # type: ignore[list-item]
    conn = AbletonConnection(fast_settings)

    with pytest.raises(CommandTimeoutError) as exc:
        conn.send_command("create_midi_track", retry=False)

    assert "may still have been applied" in str(exc.value)


def test_malformed_json_raises_invalid_response(
    monkeypatch: pytest.MonkeyPatch, fast_settings: Settings
) -> None:
    _patch_socket(monkeypatch, FakeSocket([b"{not json at all"]))
    conn = AbletonConnection(fast_settings)

    with pytest.raises(InvalidResponseError):
        conn.send_command("get_session_info", retry=False)


def test_modifying_commands_get_a_longer_timeout(fast_settings: Settings) -> None:
    """Mutating Live is marshalled onto its main thread, so it needs headroom."""
    assert fast_settings.timeout_for("create_midi_track") == fast_settings.modifying_cmd_timeout
    assert fast_settings.timeout_for("get_session_info") == fast_settings.read_cmd_timeout
    assert fast_settings.timeout_for("health_check") == fast_settings.health_check_timeout


def test_context_manager_closes_the_socket(
    monkeypatch: pytest.MonkeyPatch, fast_settings: Settings
) -> None:
    sock = FakeSocket()
    _patch_socket(monkeypatch, sock)

    with AbletonConnection(fast_settings) as conn:
        assert conn.connected

    assert sock.closed
