"""Arrangement view, locators, and warp markers.

Tools are registered by the ``@tool`` decorator, which also supplies the uniform
error handling that used to be copy-pasted into every function.
"""

from __future__ import annotations

from ._base import as_json, connection, tool


@tool
def add_warp_marker(
    track_index: int,
    clip_index: int,
    beat_time: float,
    sample_time: float | None = None,
) -> str:
    """
    Add a warp marker to an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - beat_time: The beat time position for the marker
    - sample_time: Optional sample time (calculated automatically if not provided)
    """
    params = {"track_index": track_index, "clip_index": clip_index, "beat_time": beat_time}
    if sample_time is not None:
        params["sample_time"] = sample_time
    result = connection().send_command("add_warp_marker", params)
    return as_json(result)


@tool
def create_locator(time: float, name: str = "") -> str:
    """
    Create a new locator/cue point.

    Parameters:
    - time: Position in beats for the locator
    - name: Name for the locator
    """
    result = connection().send_command("create_locator", {"time": time, "name": name})
    if result.get("created"):
        return f"Created locator '{name}' at {time}"
    return str(result.get("error", "Failed to create locator"))


@tool
def delete_locator(locator_index: int) -> str:
    """
    Delete a locator.

    Parameters:
    - locator_index: Index of the locator to delete
    """
    result = connection().send_command("delete_locator", {"locator_index": locator_index})
    if result.get("deleted"):
        return f"Deleted locator '{result.get('name')}'"
    return str(result.get("error", "Failed to delete locator"))


@tool
def delete_warp_marker(track_index: int, clip_index: int, beat_time: float) -> str:
    """
    Delete a warp marker from an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - beat_time: The beat time position of the marker to delete
    """
    result = connection().send_command(
        "delete_warp_marker",
        {"track_index": track_index, "clip_index": clip_index, "beat_time": beat_time},
    )
    return as_json(result)


@tool
def get_arrangement_length() -> str:
    """Get the length and loop settings of the arrangement."""
    result = connection().send_command("get_arrangement_length")
    return as_json(result)


@tool
def get_clip_warp_info(track_index: int, clip_index: int) -> str:
    """
    Get warp information for an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    """
    result = connection().send_command(
        "get_clip_warp_info", {"track_index": track_index, "clip_index": clip_index}
    )
    return as_json(result)


@tool
def get_locators() -> str:
    """Get all locators/cue points in the arrangement."""
    result = connection().send_command("get_locators")
    return as_json(result)


@tool
def get_warp_markers(track_index: int, clip_index: int) -> str:
    """
    Get all warp markers from an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    """
    result = connection().send_command(
        "get_warp_markers", {"track_index": track_index, "clip_index": clip_index}
    )
    return as_json(result)


@tool
def jump_to_time(time: float) -> str:
    """
    Jump to a specific time in the arrangement.

    Parameters:
    - time: Position in beats to jump to
    """
    result = connection().send_command("jump_to_time", {"time": time})
    return f"Jumped to position {result.get('current_time')}"


@tool
def set_arrangement_loop(start: float, end: float, enabled: bool = True) -> str:
    """
    Set the arrangement loop region.

    Parameters:
    - start: Loop start position in beats
    - end: Loop end position in beats
    - enabled: Whether to enable looping
    """
    result = connection().send_command(
        "set_arrangement_loop", {"start": start, "end": end, "enabled": enabled}
    )
    start_v = result.get("loop_start", 0) or 0
    length_v = result.get("loop_length", 0) or 0
    return f"Set loop from {start_v} to {start_v + length_v}"


@tool
def set_clip_warp_mode(track_index: int, clip_index: int, warp_mode: str) -> str:
    """
    Set the warp mode of an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - warp_mode: Warp mode (beats, tones, texture, repitch, complex, complex_pro)
    """
    result = connection().send_command(
        "set_clip_warp_mode",
        {"track_index": track_index, "clip_index": clip_index, "warp_mode": warp_mode},
    )
    if "error" in result:
        return f"Error: {result.get('error')}"
    return f"Set clip warp mode to {warp_mode}"


@tool
def toggle_arrangement_record() -> str:
    """Toggle arrangement record mode."""
    result = connection().send_command("toggle_arrangement_record")
    state = "on" if result.get("arrangement_record") else "off"
    return f"Arrangement record is now {state}"
