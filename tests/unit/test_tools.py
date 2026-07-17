"""Tests for the MCP tool layer.

The original server.py had 133 tools and zero tests. These cover the shared
machinery (registration, error handling, JSON rendering) and spot-check that
representative tools call the connection the way the remote script expects.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from ableton_ai import tools
from ableton_ai.exceptions import CommandFailedError, ConnectionFailedError
from ableton_ai.tools import _base


@pytest.fixture
def fake_connection(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace the shared connection so tools never touch a socket."""
    conn = MagicMock()
    conn.send_command.return_value = {}
    monkeypatch.setattr(_base, "get_ableton_connection", lambda: conn)
    return conn


def test_all_128_tools_register() -> None:
    assert len(tools.REGISTRY) == 133


def test_no_duplicate_tool_names() -> None:
    names = [fn.__name__ for fn in tools.REGISTRY]
    assert len(names) == len(set(names)), "a tool name is defined twice"


def test_every_tool_is_documented() -> None:
    undocumented = [fn.__name__ for fn in tools.REGISTRY if not (fn.__doc__ or "").strip()]
    assert not undocumented, f"tools without a docstring: {undocumented}"


def test_register_all_reports_its_count() -> None:
    mcp = MagicMock()
    count = tools.register_all(mcp)
    assert count == 133
    assert mcp.tool.call_count == 133


# -- the @tool decorator's error handling ---------------------------------


def test_tool_turns_our_errors_into_readable_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """An expected error becomes a clear message, not a traceback."""

    @_base.tool
    def boom() -> str:
        raise ConnectionFailedError("localhost", 9877)

    result = boom()
    assert isinstance(result, str)
    assert "Control Surface" in result  # the actionable part survived


def test_tool_catches_unexpected_errors_too() -> None:
    @_base.tool
    def kaboom() -> str:
        raise ValueError("something odd")

    result = kaboom()
    assert result.startswith("Error in kaboom")
    assert "something odd" in result


def test_tool_passes_through_success() -> None:
    @_base.tool
    def fine() -> str:
        return "all good"

    assert fine() == "all good"


# -- representative tools call the right command -----------------------


def test_create_midi_track_sends_expected_command(fake_connection: MagicMock) -> None:
    from ableton_ai.tools import tracks

    fake_connection.send_command.return_value = {"name": "1-MIDI", "index": 0}
    out = tracks.create_midi_track(index=-1)

    fake_connection.send_command.assert_called_once_with("create_midi_track", {"index": -1})
    assert "1-MIDI" in out


def test_set_track_volume_uses_the_volume_key(fake_connection: MagicMock) -> None:
    """Regression: this silently defaulted when called with the wrong arg name."""
    from ableton_ai.tools import tracks

    fake_connection.send_command.return_value = {"volume": 0.6}
    tracks.set_track_volume(track_index=2, volume=0.6)

    _, params = fake_connection.send_command.call_args[0]
    assert params == {"track_index": 2, "volume": 0.6}


def test_a_failed_command_surfaces_as_error_text(fake_connection: MagicMock) -> None:
    from ableton_ai.tools import tracks

    fake_connection.send_command.side_effect = CommandFailedError("delete_track", "out of range")
    out = tracks.delete_track(track_index=99)

    assert "out of range" in out


def test_as_json_is_readable(fake_connection: MagicMock) -> None:
    from ableton_ai.tools import session

    fake_connection.send_command.return_value = {"tempo": 129.0, "tracks": 7}
    out = session.get_session_info()

    assert '"tempo": 129.0' in out


def test_json_tools_do_not_pass_stray_kwargs(fake_connection: MagicMock) -> None:
    """Regression: the extraction briefly produced as_json(result, indent=2),
    which would raise TypeError at runtime since as_json takes one argument."""
    from ableton_ai.tools import session

    fake_connection.send_command.return_value = {"ok": True}
    # would raise TypeError if the stray kwarg were still there
    assert session.get_session_info()


def test_as_json_helper_handles_non_serialisable(_: Any = None) -> None:
    class Weird:
        def __str__(self) -> str:
            return "weird"

    assert "weird" in _base.as_json({"x": Weird()})


def test_flagship_features_are_exposed_as_tools() -> None:
    """Regression: probability, rack access, and scale setting were added to the
    remote script but had no MCP tool, so Claude could not reach them."""
    names = {fn.__name__ for fn in tools.REGISTRY}
    for required in (
        "add_notes_with_probability",
        "get_chain_device_parameters",
        "set_chain_device_parameter",
        "get_song_scale_names",
        "set_song_scale",
    ):
        assert required in names, f"{required} is not exposed as an MCP tool"


def test_add_notes_with_probability_sends_notes(fake_connection: MagicMock) -> None:
    from ableton_ai.tools import notes

    fake_connection.send_command.return_value = {"note_count": 2, "verified_first_note": {"pitch": 60}}
    out = notes.add_notes_with_probability(
        track_index=0,
        clip_index=0,
        notes=[{"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 80, "probability": 0.5}],
    )
    cmd, params = fake_connection.send_command.call_args[0]
    assert cmd == "add_notes_with_probability"
    assert params["notes"][0]["probability"] == 0.5
    assert "Read back" in out
