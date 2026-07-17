"""Runtime configuration, read once from the environment.

Previously these constants were duplicated across ``server.py`` and
``rest_api_server.py``, which meant changing a timeout in one place silently
left the other on the old value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _i(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    """Connection and timeout settings for talking to the remote script."""

    host: str = os.environ.get("ABLETON_HOST", "localhost")
    port: int = _i("ABLETON_PORT", 9877)

    recv_timeout: float = _f("MCP_RECV_TIMEOUT", 15.0)
    modifying_cmd_timeout: float = _f("MCP_MODIFYING_CMD_TIMEOUT", 15.0)
    read_cmd_timeout: float = _f("MCP_READ_CMD_TIMEOUT", 10.0)
    health_check_timeout: float = _f("MCP_HEALTH_CHECK_TIMEOUT", 2.0)

    command_delay: float = _f("MCP_COMMAND_DELAY", 0.05)
    retry_delay: float = _f("MCP_RETRY_DELAY", 1.0)
    max_connect_attempts: int = _i("MCP_MAX_CONNECT_ATTEMPTS", 3)

    buffer_size: int = _i("MCP_BUFFER_SIZE", 8192)

    def timeout_for(self, command_type: str) -> float:
        """Pick a timeout based on what the command does.

        Reads are quick. Anything that mutates Live has to be marshalled onto
        Live's main thread first, so it needs more headroom.
        """
        if command_type == "health_check":
            return self.health_check_timeout
        if command_type in MODIFYING_COMMANDS:
            return self.modifying_cmd_timeout
        return self.read_cmd_timeout


#: Commands that change Live's state. The remote script marshals these onto
#: Live's main thread; mutating Live from the socket thread crashes it.
MODIFYING_COMMANDS: frozenset[str] = frozenset(
    {
        "create_midi_track",
        "create_audio_track",
        "create_return_track",
        "delete_track",
        "delete_return_track",
        "duplicate_track",
        "set_track_name",
        "set_track_volume",
        "set_track_pan",
        "set_track_mute",
        "set_track_solo",
        "set_track_arm",
        "set_track_color",
        "set_send_level",
        "create_clip",
        "delete_clip",
        "duplicate_clip",
        "set_clip_name",
        "add_notes_to_clip",
        "add_notes_with_probability",
        "set_clip_automation",
        "clear_clip_automation",
        "set_device_parameter",
        "set_chain_device_parameter",
        "delete_device",
        "load_browser_item",
        "load_browser_item_to_return",
        "set_tempo",
        "set_song_scale",
        "set_song_root_note",
        "fire_clip",
        "stop_clip",
        "fire_scene",
        "start_playback",
        "stop_playback",
    }
)

settings = Settings()
