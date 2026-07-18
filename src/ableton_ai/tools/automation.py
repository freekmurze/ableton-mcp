"""Clip automation envelopes.

Tools are registered by the ``@tool`` decorator, which also supplies the uniform
error handling that used to be copy-pasted into every function.
"""

from __future__ import annotations

from ._base import as_json, connection, tool


@tool
def clear_clip_automation(track_index: int, clip_index: int, parameter_name: str) -> str:
    """
    Clear automation for a clip parameter.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - parameter_name: Name of the parameter to clear automation for
    """
    result = connection().send_command(
        "clear_clip_automation",
        {"track_index": track_index, "clip_index": clip_index, "parameter_name": parameter_name},
    )
    if "error" in result:
        return f"Error: {result.get('error')}"
    return f"Cleared automation for {parameter_name}"


@tool
def get_clip_automation(track_index: int, clip_index: int, parameter_name: str) -> str:
    """
    Get automation data for a clip parameter.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - parameter_name: Name of the parameter to get automation for
    """
    result = connection().send_command(
        "get_clip_automation",
        {"track_index": track_index, "clip_index": clip_index, "parameter_name": parameter_name},
    )
    return as_json(result)


@tool
def set_clip_automation(
    track_index: int, clip_index: int, parameter_name: str, envelope_data: list[dict[str, float]]
) -> str:
    """
    Set automation for a clip parameter.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - parameter_name: Name of the parameter to automate
    - envelope_data: List of points [{"time": 0.0, "value": 0.5}, ...]
    """
    result = connection().send_command(
        "set_clip_automation",
        {
            "track_index": track_index,
            "clip_index": clip_index,
            "parameter_name": parameter_name,
            "envelope_data": envelope_data,
        },
    )
    if "error" in result:
        return f"Error: {result.get('error')}"
    return f"Set automation with {result.get('points_added', 0)} points"


@tool
def add_lfo_automation(
    track_index: int,
    clip_index: int,
    parameter_name: str,
    device_index: int,
    shape: str = "sine",
    cycles: float = 1.0,
    min_value: float = 0.0,
    max_value: float = 1.0,
    points: int = 33,
) -> str:
    """
    Modulate any device parameter with an LFO shape, by drawing it as clip
    automation. This is the scriptable alternative to the Max for Live LFO's
    Map button, which the API cannot set.

    Parameters:
    - track_index, clip_index: the clip to draw the automation into
    - parameter_name: the parameter to modulate
    - device_index: which device on the track owns that parameter
    - shape: sine, triangle, saw, square, or random
    - cycles: how many full LFO cycles across the clip (can be fractional)
    - min_value, max_value: the range the parameter sweeps between
    - points: resolution of the drawn curve (more = smoother)
    """
    import math

    info = connection().send_command(
        "get_clip_info", {"track_index": track_index, "clip_index": clip_index}
    )
    length = float(info.get("length", 4.0))

    lo, hi = min(min_value, max_value), max(min_value, max_value)
    span = hi - lo
    n = max(2, points)

    def sample(phase: float) -> float:
        # phase in [0, 1) within one cycle
        if shape == "sine":
            return 0.5 - 0.5 * math.cos(2 * math.pi * phase)
        if shape == "triangle":
            return 1.0 - abs(2.0 * phase - 1.0)
        if shape == "saw":
            return phase
        if shape == "square":
            return 1.0 if phase < 0.5 else 0.0
        if shape == "random":
            # deterministic per-index pseudo-random, no Random import needed
            return ((int(phase * 997.0) * 131 + 7) % 100) / 99.0
        return 0.5 - 0.5 * math.cos(2 * math.pi * phase)

    envelope = []
    for i in range(n):
        t = length * i / (n - 1)
        phase = (cycles * i / (n - 1)) % 1.0
        value = lo + span * sample(phase)
        envelope.append({"time": round(t, 4), "value": round(value, 4)})

    result = connection().send_command(
        "set_clip_automation",
        {
            "track_index": track_index,
            "clip_index": clip_index,
            "parameter_name": parameter_name,
            "device_index": device_index,
            "envelope_data": envelope,
        },
    )
    if result.get("error"):
        return f"Error: {result['error']}"
    return (
        f"Drew a {shape} LFO ({cycles} cycles, {min_value} to {max_value}) on "
        f"{parameter_name} across {length} beats, {result.get('points_added')} points"
    )
