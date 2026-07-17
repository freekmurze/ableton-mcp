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
