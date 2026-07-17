"""MIDI notes, including per-note probability.

Tools are registered by the ``@tool`` decorator, which also supplies the uniform
error handling that used to be copy-pasted into every function.
"""

from __future__ import annotations

from ._base import as_json, connection, tool


@tool
def add_notes_to_clip(
    track_index: int, clip_index: int, notes: list[dict[str, int | float | bool]]
) -> str:
    """
    Add MIDI notes to a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - notes: List of note dictionaries, each with pitch, start_time, duration, velocity, and mute
    """
    connection().send_command(
        "add_notes_to_clip", {"track_index": track_index, "clip_index": clip_index, "notes": notes}
    )
    return f"Added {len(notes)} notes to clip at track {track_index}, slot {clip_index}"


@tool
def get_clip_notes(track_index: int, clip_index: int) -> str:
    """
    Get all MIDI notes from a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    result = connection().send_command(
        "get_clip_notes", {"track_index": track_index, "clip_index": clip_index}
    )
    return as_json(result)


@tool
def get_scale_notes(root: int, scale_type: str = "major") -> str:
    """
    Get the notes in a musical scale.

    Parameters:
    - root: MIDI note number for the root (0-127, where 60 = middle C)
    - scale_type: Type of scale (major, minor, dorian, phrygian, lydian, mixolydian, locrian, harmonic_minor, melodic_minor, pentatonic_major, pentatonic_minor, blues, chromatic)
    """
    result = connection().send_command("get_scale_notes", {"root": root, "scale_type": scale_type})
    return as_json(result)


@tool
def quantize_clip_notes(track_index: int, clip_index: int, grid: float = 0.25) -> str:
    """
    Quantize notes in a clip to a grid.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - grid: Grid size in beats (0.25 = 16th notes, 0.5 = 8th notes, 1.0 = quarter notes)
    """
    result = connection().send_command(
        "quantize_clip_notes", {"track_index": track_index, "clip_index": clip_index, "grid": grid}
    )
    return f"Quantized {result.get('note_count')} notes to {grid} beat grid"


@tool
def remove_all_notes(track_index: int, clip_index: int) -> str:
    """
    Remove all notes from a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    connection().send_command(
        "remove_all_notes", {"track_index": track_index, "clip_index": clip_index}
    )
    return f"Removed all notes from clip at track {track_index}, slot {clip_index}"


@tool
def remove_notes(
    track_index: int,
    clip_index: int,
    from_time: float = 0.0,
    time_span: float = 4.0,
    from_pitch: int = 0,
    pitch_span: int = 128,
) -> str:
    """
    Remove notes from a clip within a specified range.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - from_time: Start time in beats
    - time_span: Duration in beats
    - from_pitch: Starting MIDI pitch (0-127)
    - pitch_span: Number of pitches to include
    """
    connection().send_command(
        "remove_notes",
        {
            "track_index": track_index,
            "clip_index": clip_index,
            "from_time": from_time,
            "time_span": time_span,
            "from_pitch": from_pitch,
            "pitch_span": pitch_span,
        },
    )
    return f"Removed notes from clip (time: {from_time}-{from_time + time_span}, pitch: {from_pitch}-{from_pitch + pitch_span})"


@tool
def transpose_notes(track_index: int, clip_index: int, semitones: int) -> str:
    """
    Transpose all notes in a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - semitones: Number of semitones to transpose (positive = up, negative = down)
    """
    result = connection().send_command(
        "transpose_notes",
        {"track_index": track_index, "clip_index": clip_index, "semitones": semitones},
    )
    direction = "up" if semitones > 0 else "down"
    return f"Transposed {result.get('note_count')} notes {direction} by {abs(semitones)} semitones"
