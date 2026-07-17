"""Tests for the remote script's command dispatch.

The remote script runs inside Ableton, so it normally can't be imported here.
We mock the _Framework.ControlSurface base and load it off-Live, which lets us
test the dispatch table and threading routing without a running Ableton. This
is the only automated coverage the remote script has.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

REMOTE_SCRIPT = Path(__file__).resolve().parents[2] / "remote_script" / "__init__.py"


@pytest.fixture(scope="module")
def remote_class() -> Any:
    """Load the remote script class with the Ableton framework mocked out."""
    fw = types.ModuleType("_Framework")
    cs = types.ModuleType("_Framework.ControlSurface")

    class ControlSurface:
        def __init__(self, *a: Any, **k: Any) -> None: ...
        def log_message(self, *a: Any) -> None: ...
        def show_message(self, *a: Any) -> None: ...

    cs.ControlSurface = ControlSurface  # type: ignore[attr-defined]
    fw.ControlSurface = cs  # type: ignore[attr-defined]
    sys.modules["_Framework"] = fw
    sys.modules["_Framework.ControlSurface"] = cs

    spec = importlib.util.spec_from_file_location("remote_script_under_test", REMOTE_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.AbletonAI


@pytest.fixture
def instance(remote_class: Any) -> Any:
    """A remote-script instance that never opened a socket, with main-thread
    scheduling collapsed to run inline."""
    obj = remote_class.__new__(remote_class)
    obj.schedule_message = lambda delay, fn: fn()
    return obj


def test_unknown_command_errors(instance: Any) -> None:
    result = instance._process_command({"type": "no_such_command", "params": {}})
    assert result["status"] == "error"
    assert "Unknown command" in result["message"]


def test_read_command_runs_directly(instance: Any) -> None:
    instance._get_session_info = lambda: {"tempo": 120}
    result = instance._process_command({"type": "get_session_info", "params": {}})
    assert result["status"] == "success"
    assert result["result"] == {"tempo": 120}


def test_write_command_is_scheduled_and_returns_result(instance: Any) -> None:
    calls = []
    instance._create_midi_track = lambda index: calls.append(index) or {"name": "1-MIDI"}
    result = instance._process_command({"type": "create_midi_track", "params": {"index": -1}})
    assert result["status"] == "success"
    assert result["result"]["name"] == "1-MIDI"
    assert calls == [-1]


def test_dispatch_table_marks_reads_and_writes(instance: Any) -> None:
    assert instance._DISPATCH["get_session_info"] == ("_rd_get_session_info", False)
    assert instance._DISPATCH["create_midi_track"] == ("_wr_create_midi_track", True)


def test_orphan_command_stays_unreachable(instance: Any) -> None:
    """load_instrument_or_effect had a handler but was never whitelisted, so it
    was unreachable. The refactor must not accidentally expose it."""
    assert "load_instrument_or_effect" not in instance._DISPATCH


def test_state_changing_commands_route_to_main_thread(instance: Any) -> None:
    """A representative set of mutating commands must be flagged for the main
    thread, because mutating Live off the main thread crashes it."""
    for cmd in ("create_midi_track", "set_track_volume", "add_notes_to_clip", "set_tempo"):
        assert instance._DISPATCH[cmd][1] is True, f"{cmd} must run on the main thread"


def test_write_note_tuples_uses_modern_api_on_live11(instance: object) -> None:
    """On Live 11+ (clip has add_new_notes) the helper must use it, not the
    legacy set_notes that triggers Ableton's data-loss warning."""

    class ModernClip:
        length = 4.0

        def __init__(self) -> None:
            self.added: object = None
            self.set_notes_called = False

        def remove_notes_extended(self, *a: object) -> None: ...
        def add_new_notes(self, specs: object) -> None:
            self.added = specs

        def set_notes(self, notes: object) -> None:
            self.set_notes_called = True

    import sys

    Live = type(sys)("Live")
    Clip = type(sys)("Live.Clip")

    class MidiNoteSpecification:
        def __init__(self, **kw: object) -> None:
            self.kw = kw

    Clip.MidiNoteSpecification = MidiNoteSpecification
    Live.Clip = Clip
    sys.modules["Live"] = Live
    sys.modules["Live.Clip"] = Clip

    clip = ModernClip()
    count = instance._write_note_tuples(clip, [(60, 0.0, 1.0, 100, False)], replace=True)

    assert count == 1
    assert clip.added is not None, "should have used add_new_notes"
    assert clip.set_notes_called is False, "must not use legacy set_notes on Live 11+"


def test_write_note_tuples_does_not_recurse_on_legacy_clip(instance: object) -> None:
    """A clip without add_new_notes must fall through to set_notes exactly once,
    not call the helper again (the regex refactor briefly made this infinite)."""

    class LegacyClip:
        length = 4.0

        def __init__(self) -> None:
            self.set_notes_calls = 0

        def remove_notes(self, *a: object) -> None: ...
        def set_notes(self, notes: object) -> None:
            self.set_notes_calls += 1

    clip = LegacyClip()
    count = instance._write_note_tuples(clip, [(60, 0.0, 1.0, 100, False)], replace=True)

    assert count == 1
    assert clip.set_notes_calls == 1
