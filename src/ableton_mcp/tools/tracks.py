"""Track lifecycle, mixer, sends, returns, groups, and routing.

Tools are registered by the ``@tool`` decorator, which also supplies the uniform
error handling that used to be copy-pasted into every function.
"""

from __future__ import annotations

from ._base import as_json, connection, tool


@tool
def create_audio_track(index: int = -1) -> str:
    """
    Create a new audio track in the Ableton session.

    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    result = connection().send_command("create_audio_track", {"index": index})
    return (
        f"Created new audio track: {result.get('name', 'unknown')} at index {result.get('index')}"
    )


@tool
def create_group_track(track_indices: list[int], name: str = "Group") -> str:
    """
    Create a group track containing the specified tracks.

    Parameters:
    - track_indices: List of track indices to group
    - name: Name for the group track
    """
    result = connection().send_command(
        "create_group_track", {"track_indices": track_indices, "name": name}
    )
    if "error" in result:
        return f"Error: {result.get('error')}"
    return f"Created group '{name}' at index {result.get('group_track_index')}"


@tool
def create_midi_track(index: int = -1) -> str:
    """
    Create a new MIDI track in the Ableton session.

    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    result = connection().send_command("create_midi_track", {"index": index})
    return f"Created new MIDI track: {result.get('name', 'unknown')}"


@tool
def delete_track(track_index: int) -> str:
    """
    Delete a track.

    Parameters:
    - track_index: The index of the track to delete
    """
    result = connection().send_command("delete_track", {"track_index": track_index})
    return f"Deleted track '{result.get('track_name')}' at index {track_index}"


@tool
def duplicate_track(track_index: int) -> str:
    """
    Duplicate a track with all its clips and devices.

    Parameters:
    - track_index: The index of the track to duplicate
    """
    result = connection().send_command("duplicate_track", {"track_index": track_index})
    return f"Duplicated track {track_index}, new track '{result.get('new_name')}' at index {result.get('new_index')}"


@tool
def flatten_track(track_index: int) -> str:
    """
    Flatten a frozen track (convert freeze to permanent audio).
    The track must be frozen first.

    Parameters:
    - track_index: The index of the track to flatten
    """
    result = connection().send_command("flatten_track", {"track_index": track_index})
    if result.get("success"):
        return f"Flattened track {track_index} '{result.get('name')}'"
    return f"Could not flatten track: {result.get('message')}"


@tool
def fold_track(track_index: int) -> str:
    """
    Fold (collapse) a group track.

    Parameters:
    - track_index: The index of the group track
    """
    result = connection().send_command("fold_track", {"track_index": track_index})
    if "error" in result:
        return f"Error: {result.get('error')}"
    return f"Folded track {track_index}"


@tool
def freeze_track(track_index: int) -> str:
    """
    Freeze a track (render all devices to audio for CPU optimization).

    Parameters:
    - track_index: The index of the track to freeze
    """
    result = connection().send_command("freeze_track", {"track_index": track_index})
    if result.get("success"):
        return f"Froze track {track_index} '{result.get('name')}'"
    return f"Could not freeze track: {result.get('message')}"


@tool
def get_master_info() -> str:
    """Get information about the master track including volume, pan, and devices."""
    result = connection().send_command("get_master_info")
    return as_json(result)


@tool
def get_return_track_info(return_index: int) -> str:
    """
    Get detailed information about a return track.

    Parameters:
    - return_index: The index of the return track
    """
    result = connection().send_command("get_return_track_info", {"return_index": return_index})
    return as_json(result)


@tool
def get_return_tracks() -> str:
    """Get information about all return (aux) tracks."""
    result = connection().send_command("get_return_tracks")
    return as_json(result)


@tool
def get_send_level(track_index: int, send_index: int) -> str:
    """
    Get the send level from a track to a return track.

    Parameters:
    - track_index: The index of the source track
    - send_index: The index of the send (0=A, 1=B, etc.)
    """
    result = connection().send_command(
        "get_send_level", {"track_index": track_index, "send_index": send_index}
    )
    return as_json(result)


@tool
def get_track_color(track_index: int) -> str:
    """
    Get the color of a track.

    Parameters:
    - track_index: The index of the track
    """
    result = connection().send_command("get_track_color", {"track_index": track_index})
    return as_json(result)


@tool
def get_track_info(track_index: int) -> str:
    """
    Get detailed information about a specific track in Ableton.

    Parameters:
    - track_index: The index of the track to get information about
    """
    result = connection().send_command("get_track_info", {"track_index": track_index})
    return as_json(result)


@tool
def get_track_input_routing(track_index: int) -> str:
    """
    Get the input routing of a track.

    Parameters:
    - track_index: The index of the track
    """
    result = connection().send_command("get_track_input_routing", {"track_index": track_index})
    return as_json(result)


@tool
def get_track_monitoring(track_index: int) -> str:
    """
    Get the monitoring mode of a track.

    Parameters:
    - track_index: The index of the track
    """
    result = connection().send_command("get_track_monitoring", {"track_index": track_index})
    return as_json(result)


@tool
def get_track_output_routing(track_index: int) -> str:
    """
    Get the output routing of a track.

    Parameters:
    - track_index: The index of the track
    """
    result = connection().send_command("get_track_output_routing", {"track_index": track_index})
    return as_json(result)


@tool
def select_track(track_index: int) -> str:
    """
    Select a track.

    Parameters:
    - track_index: The index of the track to select
    """
    result = connection().send_command("select_track", {"track_index": track_index})
    return f"Selected track '{result.get('track_name')}' at index {track_index}"


@tool
def set_master_pan(pan: float) -> str:
    """
    Set the master track panning.

    Parameters:
    - pan: Pan position from -1.0 (full left) to 1.0 (full right). 0.0 is center.
    """
    if not -1 <= pan <= 1:
        return "Error: Pan must be between -1.0 and 1.0"
    result = connection().send_command("set_master_pan", {"pan": pan})
    return f"Master pan set to {result.get('panning', pan):.2f}"


@tool
def set_master_volume(volume: float) -> str:
    """
    Set the master track volume.

    Parameters:
    - volume: Volume level from 0.0 (silent) to 1.0 (unity gain). 0.85 is Ableton's default.
    """
    if not 0 <= volume <= 1:
        return "Error: Volume must be between 0.0 and 1.0"
    result = connection().send_command("set_master_volume", {"volume": volume})
    return f"Master volume set to {result.get('volume', volume):.2f}"


@tool
def set_return_pan(return_index: int, pan: float) -> str:
    """
    Set the panning of a return track.

    Parameters:
    - return_index: The index of the return track
    - pan: The pan position (-1.0 = left, 0.0 = center, 1.0 = right)
    """
    result = connection().send_command("set_return_pan", {"return_index": return_index, "pan": pan})
    return f"Set return track {return_index} pan to {result.get('panning')}"


@tool
def set_return_volume(return_index: int, volume: float) -> str:
    """
    Set the volume of a return track.

    Parameters:
    - return_index: The index of the return track
    - volume: The volume level (0.0 to 1.0)
    """
    result = connection().send_command(
        "set_return_volume", {"return_index": return_index, "volume": volume}
    )
    return f"Set return track {return_index} volume to {result.get('volume')}"


@tool
def set_send_level(track_index: int, send_index: int, level: float) -> str:
    """
    Set the send level from a track to a return track.

    Parameters:
    - track_index: The index of the source track
    - send_index: The index of the send (corresponds to return track index)
    - level: The send level (0.0 to 1.0)
    """
    result = connection().send_command(
        "set_send_level", {"track_index": track_index, "send_index": send_index, "level": level}
    )
    return f"Set track {track_index} send {send_index} to {result.get('level')}"


@tool
def set_track_arm(track_index: int, arm: bool) -> str:
    """
    Set the arm (record enable) state of a track.

    Parameters:
    - track_index: The index of the track
    - arm: True to arm for recording, False to disarm
    """
    result = connection().send_command("set_track_arm", {"track_index": track_index, "arm": arm})
    if "error" in result:
        return f"Track {track_index}: {result.get('error')}"
    state = "armed" if result.get("arm") else "disarmed"
    return f"Track {track_index} is now {state}"


@tool
def set_track_color(track_index: int, color: int) -> str:
    """
    Set the color of a track.

    Parameters:
    - track_index: The index of the track
    - color: The color index (0-69 in Ableton's color palette)
    """
    result = connection().send_command(
        "set_track_color", {"track_index": track_index, "color": color}
    )
    return f"Set track {track_index} color to {result.get('color_index')}"


@tool
def set_track_input_routing(track_index: int, routing_type: str, routing_channel: str = "") -> str:
    """
    Set the input routing of a track.

    Parameters:
    - track_index: The index of the track
    - routing_type: The input routing type (use get_available_inputs to see options)
    - routing_channel: The input channel (optional)
    """
    result = connection().send_command(
        "set_track_input_routing",
        {
            "track_index": track_index,
            "routing_type": routing_type,
            "routing_channel": routing_channel,
        },
    )
    return f"Set track {track_index} input to {result.get('input_routing_type')}"


@tool
def set_track_monitoring(track_index: int, monitoring: str) -> str:
    """
    Set the monitoring mode of a track.

    Parameters:
    - track_index: The index of the track
    - monitoring: Monitoring mode (in, auto, off)
    """
    result = connection().send_command(
        "set_track_monitoring", {"track_index": track_index, "monitoring": monitoring}
    )
    if "error" in result:
        return f"Error: {result.get('error')}"
    return f"Set track {track_index} monitoring to {monitoring}"


@tool
def set_track_mute(track_index: int, mute: bool) -> str:
    """
    Set the mute state of a track.

    Parameters:
    - track_index: The index of the track
    - mute: True to mute, False to unmute
    """
    result = connection().send_command("set_track_mute", {"track_index": track_index, "mute": mute})
    state = "muted" if result.get("mute") else "unmuted"
    return f"Track {track_index} is now {state}"


@tool
def set_track_name(track_index: int, name: str) -> str:
    """
    Set the name of a track.

    Parameters:
    - track_index: The index of the track to rename
    - name: The new name for the track
    """
    result = connection().send_command("set_track_name", {"track_index": track_index, "name": name})
    return f"Renamed track to: {result.get('name', name)}"


@tool
def set_track_output_routing(track_index: int, routing_type: str, routing_channel: str = "") -> str:
    """
    Set the output routing of a track.

    Parameters:
    - track_index: The index of the track
    - routing_type: The output routing type (use get_available_outputs to see options)
    - routing_channel: The output channel (optional)
    """
    result = connection().send_command(
        "set_track_output_routing",
        {
            "track_index": track_index,
            "routing_type": routing_type,
            "routing_channel": routing_channel,
        },
    )
    return f"Set track {track_index} output to {result.get('output_routing_type')}"


@tool
def set_track_pan(track_index: int, pan: float) -> str:
    """
    Set the panning of a track.

    Parameters:
    - track_index: The index of the track
    - pan: Pan position from -1.0 (full left) to 1.0 (full right). 0.0 is center.
    """
    result = connection().send_command("set_track_pan", {"track_index": track_index, "pan": pan})
    return f"Track {track_index} pan set to {result.get('panning', pan):.2f}"


@tool
def set_track_solo(track_index: int, solo: bool) -> str:
    """
    Set the solo state of a track.

    Parameters:
    - track_index: The index of the track
    - solo: True to solo, False to unsolo
    """
    result = connection().send_command("set_track_solo", {"track_index": track_index, "solo": solo})
    state = "soloed" if result.get("solo") else "unsoloed"
    return f"Track {track_index} is now {state}"


@tool
def set_track_volume(track_index: int, volume: float) -> str:
    """
    Set the volume of a track.

    Parameters:
    - track_index: The index of the track
    - volume: Volume level from 0.0 (silent) to 1.0 (unity gain). 0.85 is Ableton's default.
    """
    result = connection().send_command(
        "set_track_volume", {"track_index": track_index, "volume": volume}
    )
    return f"Track {track_index} volume set to {result.get('volume', volume):.2f}"


@tool
def unfold_track(track_index: int) -> str:
    """
    Unfold (expand) a group track.

    Parameters:
    - track_index: The index of the group track
    """
    result = connection().send_command("unfold_track", {"track_index": track_index})
    if "error" in result:
        return f"Error: {result.get('error')}"
    return f"Unfolded track {track_index}"
