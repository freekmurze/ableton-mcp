"""Higher-level musical helpers built on the primitives.

Tools are registered by the ``@tool`` decorator, which also supplies the uniform
error handling that used to be copy-pasted into every function.
"""

from __future__ import annotations

from ._base import connection, tool


@tool
def generate_bassline(
    track_index: int,
    clip_index: int,
    root: int = 36,
    scale_type: str = "minor",
    length: float = 4.0,
) -> str:
    """
    Generate a bassline pattern and add it to a clip.

    Parameters:
    - track_index: The index of the track (should be a bass track)
    - clip_index: The index of the clip slot
    - root: Root note MIDI number (36 = C1, common bass range)
    - scale_type: Scale to use (minor, major, dorian, pentatonic_minor, blues)
    - length: Pattern length in beats
    """
    result = connection().send_command(
        "generate_bassline",
        {
            "track_index": track_index,
            "clip_index": clip_index,
            "root": root,
            "scale_type": scale_type,
            "length": length,
        },
    )
    return f"Generated {scale_type} bassline with {result.get('note_count')} notes"
