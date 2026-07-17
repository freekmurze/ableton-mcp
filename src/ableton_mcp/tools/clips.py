"""Clip slots: create, delete, duplicate, launch, and properties.

Tools are registered by the ``@tool`` decorator, which also supplies the uniform
error handling that used to be copy-pasted into every function.
"""

from __future__ import annotations

from ._base import as_json, connection, tool


@tool
def create_clip(track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Create a new MIDI clip in the specified track and clip slot.

    Parameters:
    - track_index: The index of the track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - length: The length of the clip in beats (default: 4.0)
    """
    connection().send_command(
        "create_clip", {"track_index": track_index, "clip_index": clip_index, "length": length}
    )
    return f"Created new clip at track {track_index}, slot {clip_index} with length {length} beats"


@tool
def delete_clip(track_index: int, clip_index: int) -> str:
    """
    Delete a clip from a clip slot.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    result = connection().send_command(
        "delete_clip", {"track_index": track_index, "clip_index": clip_index}
    )
    return f"Deleted clip '{result.get('clip_name')}' from track {track_index}, slot {clip_index}"


@tool
def duplicate_clip(track_index: int, clip_index: int) -> str:
    """
    Duplicate a clip to the next empty slot.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    result = connection().send_command(
        "duplicate_clip", {"track_index": track_index, "clip_index": clip_index}
    )
    return f"Duplicated clip to slot {result.get('new_index')}"


@tool
def fire_clip(track_index: int, clip_index: int) -> str:
    """
    Start playing a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    connection().send_command("fire_clip", {"track_index": track_index, "clip_index": clip_index})
    return f"Started playing clip at track {track_index}, slot {clip_index}"


@tool
def get_clip_color(track_index: int, clip_index: int) -> str:
    """
    Get the color of a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot
    """
    result = connection().send_command(
        "get_clip_color", {"track_index": track_index, "clip_index": clip_index}
    )
    return as_json(result)


@tool
def get_clip_gain(track_index: int, clip_index: int) -> str:
    """
    Get the gain of an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    """
    result = connection().send_command(
        "get_clip_gain", {"track_index": track_index, "clip_index": clip_index}
    )
    return as_json(result)


@tool
def get_clip_loop(track_index: int, clip_index: int) -> str:
    """
    Get the loop settings of a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot
    """
    result = connection().send_command(
        "get_clip_loop", {"track_index": track_index, "clip_index": clip_index}
    )
    return as_json(result)


@tool
def get_clip_pitch(track_index: int, clip_index: int) -> str:
    """
    Get the pitch shift of an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    """
    result = connection().send_command(
        "get_clip_pitch", {"track_index": track_index, "clip_index": clip_index}
    )
    return as_json(result)


@tool
def humanize_clip_timing(track_index: int, clip_index: int, amount: float = 0.05) -> str:
    """
    Add random timing variation to notes in a clip for a more human feel.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - amount: Amount of timing variation in beats (0.05 = subtle, 0.1 = moderate, 0.2 = heavy)
    """
    result = connection().send_command(
        "humanize_clip_timing",
        {"track_index": track_index, "clip_index": clip_index, "amount": amount},
    )
    return f"Humanized timing of {result.get('note_count')} notes with amount {amount}"


@tool
def humanize_clip_velocity(track_index: int, clip_index: int, amount: float = 0.1) -> str:
    """
    Add random velocity variation to notes in a clip for a more human feel.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - amount: Amount of velocity variation (0.1 = +/-10%, 0.2 = +/-20%)
    """
    result = connection().send_command(
        "humanize_clip_velocity",
        {"track_index": track_index, "clip_index": clip_index, "amount": amount},
    )
    return f"Humanized velocity of {result.get('note_count')} notes with amount {amount}"


@tool
def select_clip(track_index: int, clip_index: int) -> str:
    """
    Select a clip slot.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot
    """
    result = connection().send_command(
        "select_clip", {"track_index": track_index, "clip_index": clip_index}
    )
    has_clip = "with clip" if result.get("has_clip") else "empty"
    return f"Selected clip slot at track {track_index}, slot {clip_index} ({has_clip})"


@tool
def set_clip_color(track_index: int, clip_index: int, color: int) -> str:
    """
    Set the color of a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - color: The color index (0-69 in Ableton's color palette)
    """
    result = connection().send_command(
        "set_clip_color", {"track_index": track_index, "clip_index": clip_index, "color": color}
    )
    return f"Set clip color to {result.get('color_index')}"


@tool
def set_clip_gain(track_index: int, clip_index: int, gain: float) -> str:
    """
    Set the gain of an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - gain: Gain in dB (e.g., -6.0 for -6dB, 3.0 for +3dB)
    """
    result = connection().send_command(
        "set_clip_gain", {"track_index": track_index, "clip_index": clip_index, "gain": gain}
    )
    if "error" in result:
        return f"Error: {result.get('error')}"
    return f"Set clip gain to {gain}dB"


@tool
def set_clip_loop(
    track_index: int,
    clip_index: int,
    loop_start: float = 0.0,
    loop_end: float = 4.0,
    looping: bool = True,
) -> str:
    """
    Set the loop settings of a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - loop_start: The start point of the loop in beats
    - loop_end: The end point of the loop in beats
    - looping: Whether looping is enabled
    """
    result = connection().send_command(
        "set_clip_loop",
        {
            "track_index": track_index,
            "clip_index": clip_index,
            "loop_start": loop_start,
            "loop_end": loop_end,
            "looping": looping,
        },
    )
    return f"Set clip loop: {result.get('loop_start')} - {result.get('loop_end')}, looping: {result.get('looping')}"


@tool
def set_clip_name(track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - name: The new name for the clip
    """
    connection().send_command(
        "set_clip_name", {"track_index": track_index, "clip_index": clip_index, "name": name}
    )
    return f"Renamed clip at track {track_index}, slot {clip_index} to '{name}'"


@tool
def set_clip_pitch(track_index: int, clip_index: int, pitch: int) -> str:
    """
    Set the pitch shift of an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - pitch: Pitch shift in semitones (-48 to +48)
    """
    result = connection().send_command(
        "set_clip_pitch", {"track_index": track_index, "clip_index": clip_index, "pitch": pitch}
    )
    if "error" in result:
        return f"Error: {result.get('error')}"
    return f"Set clip pitch to {pitch} semitones"


@tool
def stop_clip(track_index: int, clip_index: int) -> str:
    """
    Stop playing a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    connection().send_command("stop_clip", {"track_index": track_index, "clip_index": clip_index})
    return f"Stopped clip at track {track_index}, slot {clip_index}"
