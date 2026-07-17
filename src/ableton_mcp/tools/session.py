"""Session, transport, tempo, scenes, and song-level settings.

Tools are registered by the ``@tool`` decorator, which also supplies the uniform
error handling that used to be copy-pasted into every function.
"""

from __future__ import annotations

from ._base import as_json, connection, tool


@tool
def apply_groove(track_index: int, clip_index: int, groove_index: int) -> str:
    """
    Apply a groove to a clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - groove_index: The index of the groove from the groove pool
    """
    result = connection().send_command(
        "apply_groove",
        {"track_index": track_index, "clip_index": clip_index, "groove_index": groove_index},
    )
    if "error" in result:
        return f"Error: {result.get('error')}"
    return f"Applied groove '{result.get('groove_name')}' to clip"


@tool
def capture_midi() -> str:
    """Capture MIDI that was played recently (like Ableton's Capture feature)."""
    result = connection().send_command("capture_midi")
    if result.get("captured"):
        return "Captured MIDI"
    return str(result.get("error", "Failed to capture MIDI"))


@tool
def commit_groove(track_index: int, clip_index: int) -> str:
    """
    Commit groove quantization to clip notes (make it permanent).

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    """
    result = connection().send_command(
        "commit_groove", {"track_index": track_index, "clip_index": clip_index}
    )
    if "error" in result:
        return f"Error: {result.get('error')}"
    return "Committed groove to clip"


@tool
def create_scene(index: int = -1) -> str:
    """
    Create a new scene.

    Parameters:
    - index: The index to insert the scene at (-1 = end of list)
    """
    result = connection().send_command("create_scene", {"index": index})
    return f"Created new scene '{result.get('name')}' at index {result.get('index')}"


@tool
def delete_scene(scene_index: int) -> str:
    """
    Delete a scene.

    Parameters:
    - scene_index: The index of the scene to delete
    """
    result = connection().send_command("delete_scene", {"scene_index": scene_index})
    return f"Deleted scene '{result.get('scene_name')}' at index {scene_index}"


@tool
def duplicate_scene(scene_index: int) -> str:
    """
    Duplicate a scene.

    Parameters:
    - scene_index: The index of the scene to duplicate
    """
    result = connection().send_command("duplicate_scene", {"scene_index": scene_index})
    return f"Duplicated scene {scene_index}, new scene at index {result.get('new_index')}"


@tool
def fire_scene(scene_index: int) -> str:
    """
    Fire (trigger) a scene to play all clips in that row.

    Parameters:
    - scene_index: The index of the scene to fire
    """
    result = connection().send_command("fire_scene", {"scene_index": scene_index})
    return f"Fired scene '{result.get('scene_name')}' at index {scene_index}"


@tool
def focus_view(view_name: str) -> str:
    """
    Focus a specific view in Ableton.

    Parameters:
    - view_name: The name of the view (Session, Arranger, Detail, etc.)
    """
    connection().send_command("focus_view", {"view_name": view_name})
    return f"Focused view: {view_name}"


@tool
def get_all_scenes() -> str:
    """Get information about all scenes in the session."""
    result = connection().send_command("get_all_scenes")
    return as_json(result)


@tool
def get_available_inputs(track_index: int) -> str:
    """
    Get available input routing options for a track.

    Parameters:
    - track_index: The index of the track
    """
    result = connection().send_command("get_available_inputs", {"track_index": track_index})
    return as_json(result)


@tool
def get_available_outputs(track_index: int) -> str:
    """
    Get available output routing options for a track.

    Parameters:
    - track_index: The index of the track
    """
    result = connection().send_command("get_available_outputs", {"track_index": track_index})
    return as_json(result)


@tool
def get_cpu_load() -> str:
    """Get the current CPU load of Ableton."""
    result = connection().send_command("get_cpu_load")
    if result.get("cpu_load") is not None:
        return f"CPU Load: {result.get('cpu_load')}%"
    return "CPU load information not available"


@tool
def get_current_view() -> str:
    """Get information about the current view state (selected track, scene, etc.)."""
    result = connection().send_command("get_current_view")
    return as_json(result)


@tool
def get_groove_pool() -> str:
    """Get available grooves from the groove pool."""
    result = connection().send_command("get_groove_pool", {})
    return as_json(result)


@tool
def get_metronome_state() -> str:
    """Get the current metronome state."""
    result = connection().send_command("get_metronome_state")
    if result.get("enabled") is not None:
        state = "on" if result.get("enabled") else "off"
        return f"Metronome is {state}"
    return "Metronome state not available"


@tool
def get_playback_position() -> str:
    """Get the current playback position and transport state."""
    result = connection().send_command("get_playback_position")
    return as_json(result)


@tool
def get_scene_color(scene_index: int) -> str:
    """
    Get the color of a scene.

    Parameters:
    - scene_index: The index of the scene
    """
    result = connection().send_command("get_scene_color", {"scene_index": scene_index})
    return as_json(result)


@tool
def get_session_info() -> str:
    """Get detailed information about the current Ableton session"""
    result = connection().send_command("get_session_info")
    return as_json(result)


@tool
def get_session_path() -> str:
    """Get the file path of the current session."""
    result = connection().send_command("get_session_path")
    return as_json(result)


@tool
def health_check() -> str:
    """Check if Ableton Live is connected and responsive."""
    result = connection().send_command("health_check")
    return as_json(
        {
            "connected": True,
            "status": result.get("status", "ok"),
            "tempo": result.get("tempo"),
            "is_playing": result.get("is_playing"),
            "track_count": result.get("track_count"),
        }
    )


@tool
def is_session_modified() -> str:
    """Check if the session has unsaved changes."""
    result = connection().send_command("is_session_modified")
    if result.get("modified") is not None:
        status = "has unsaved changes" if result.get("modified") else "is saved"
        return f"Session {status}"
    return "Session modification status not available"


@tool
def redo() -> str:
    """Redo the last undone operation in Ableton."""
    result = connection().send_command("redo")
    if result.get("redone"):
        return "Redid last operation"
    return str(result.get("error", "Nothing to redo"))


@tool
def select_scene(scene_index: int) -> str:
    """
    Select a scene.

    Parameters:
    - scene_index: The index of the scene to select
    """
    result = connection().send_command("select_scene", {"scene_index": scene_index})
    return f"Selected scene '{result.get('scene_name')}' at index {scene_index}"


@tool
def set_metronome(enabled: bool) -> str:
    """
    Turn the metronome on or off.

    Parameters:
    - enabled: True to enable, False to disable
    """
    result = connection().send_command("set_metronome", {"enabled": enabled})
    state = "on" if result.get("enabled") else "off"
    return f"Metronome is now {state}"


@tool
def set_overdub(enabled: bool) -> str:
    """
    Set overdub mode.

    Parameters:
    - enabled: True to enable overdub, False to disable
    """
    result = connection().send_command("set_overdub", {"enabled": enabled})
    if "error" in result:
        return str(result.get("error"))
    state = "enabled" if result.get("overdub") else "disabled"
    return f"Overdub is now {state}"


@tool
def set_scene_color(scene_index: int, color: int) -> str:
    """
    Set the color of a scene.

    Parameters:
    - scene_index: The index of the scene
    - color: The color index (0-69 in Ableton's color palette)
    """
    result = connection().send_command(
        "set_scene_color", {"scene_index": scene_index, "color": color}
    )
    return f"Set scene {scene_index} color to {result.get('color_index')}"


@tool
def set_scene_name(scene_index: int, name: str) -> str:
    """
    Set the name of a scene.

    Parameters:
    - scene_index: The index of the scene to rename
    - name: The new name for the scene
    """
    result = connection().send_command("set_scene_name", {"scene_index": scene_index, "name": name})
    return f"Renamed scene {scene_index} to '{result.get('name')}'"


@tool
def set_tempo(tempo: float) -> str:
    """
    Set the tempo of the Ableton session.

    Parameters:
    - tempo: The new tempo in BPM
    """
    connection().send_command("set_tempo", {"tempo": tempo})
    return f"Set tempo to {tempo} BPM"


@tool
def start_playback() -> str:
    """Start playing the Ableton session."""
    connection().send_command("start_playback")
    return "Started playback"


@tool
def start_recording() -> str:
    """Start recording in Ableton."""
    result = connection().send_command("start_recording")
    return "Started recording" if result.get("recording") else "Failed to start recording"


@tool
def stop_playback() -> str:
    """Stop playing the Ableton session."""
    connection().send_command("stop_playback")
    return "Stopped playback"


@tool
def stop_recording() -> str:
    """Stop recording in Ableton."""
    connection().send_command("stop_recording")
    return "Stopped recording"


@tool
def stop_scene(scene_index: int) -> str:
    """
    Stop all clips in a scene.

    Parameters:
    - scene_index: The index of the scene to stop
    """
    connection().send_command("stop_scene", {"scene_index": scene_index})
    return f"Stopped scene at index {scene_index}"


@tool
def toggle_session_record() -> str:
    """Toggle session record mode."""
    result = connection().send_command("toggle_session_record")
    if "error" in result:
        return str(result.get("error"))
    state = "on" if result.get("session_record") else "off"
    return f"Session record is now {state}"


@tool
def unarm_all() -> str:
    """
    Unarm all tracks in the session.
    Useful before recording to ensure only specific tracks will record.
    """
    result = connection().send_command("unarm_all", {})
    if result.get("success"):
        return f"Unarmed {result.get('unarmed_count', 0)} tracks"
    return f"Could not unarm tracks: {result.get('error')}"


@tool
def undo() -> str:
    """Undo the last operation in Ableton."""
    result = connection().send_command("undo")
    if result.get("undone"):
        return "Undid last operation"
    return str(result.get("error", "Nothing to undo"))
