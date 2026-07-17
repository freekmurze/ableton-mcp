"""Devices, their parameters, and rack internals.

Tools are registered by the ``@tool`` decorator, which also supplies the uniform
error handling that used to be copy-pasted into every function.
"""

from __future__ import annotations

from ._base import as_json, connection, tool


@tool
def delete_device(track_index: int, device_index: int) -> str:
    """
    Delete a device from a track.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device to delete
    """
    result = connection().send_command(
        "delete_device", {"track_index": track_index, "device_index": device_index}
    )
    return f"Deleted device '{result.get('device_name')}' from track {track_index}"


@tool
def generate_drum_pattern(
    track_index: int, clip_index: int, style: str = "basic", length: float = 4.0
) -> str:
    """
    Generate a drum pattern and add it to a clip.

    Parameters:
    - track_index: The index of the track (should be a drum track)
    - clip_index: The index of the clip slot
    - style: Pattern style (basic, house, hiphop, dnb, random)
    - length: Pattern length in beats
    """
    result = connection().send_command(
        "generate_drum_pattern",
        {"track_index": track_index, "clip_index": clip_index, "style": style, "length": length},
    )
    return f"Generated {style} drum pattern with {result.get('note_count')} notes"


@tool
def get_device_by_name(track_index: int, device_name: str) -> str:
    """
    Find a device by name and get its parameters.

    Parameters:
    - track_index: The index of the track
    - device_name: The name of the device to find
    """
    result = connection().send_command(
        "get_device_by_name", {"track_index": track_index, "device_name": device_name}
    )
    return as_json(result)


@tool
def get_device_parameters(track_index: int, device_index: int) -> str:
    """
    Get all parameters from a device on a track.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    """
    result = connection().send_command(
        "get_device_parameters", {"track_index": track_index, "device_index": device_index}
    )
    return as_json(result)


@tool
def get_rack_chains(track_index: int, device_index: int) -> str:
    """
    Get chains from an instrument or effect rack.

    Parameters:
    - track_index: The index of the track
    - device_index: The index of the rack device
    """
    result = connection().send_command(
        "get_rack_chains", {"track_index": track_index, "device_index": device_index}
    )
    return as_json(result)


@tool
def move_device_left(track_index: int, device_index: int) -> str:
    """
    Move a device one position to the left in the device chain.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device to move
    """
    result = connection().send_command(
        "move_device_left", {"track_index": track_index, "device_index": device_index}
    )
    if result.get("success"):
        return f"Moved device to position {result.get('new_index')}"
    return f"Could not move device: {result.get('error')}"


@tool
def move_device_right(track_index: int, device_index: int) -> str:
    """
    Move a device one position to the right in the device chain.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device to move
    """
    result = connection().send_command(
        "move_device_right", {"track_index": track_index, "device_index": device_index}
    )
    if result.get("success"):
        return f"Moved device to position {result.get('new_index')}"
    return f"Could not move device: {result.get('error')}"


@tool
def select_rack_chain(track_index: int, device_index: int, chain_index: int) -> str:
    """
    Select a chain in a rack device.

    Parameters:
    - track_index: The index of the track
    - device_index: The index of the rack device
    - chain_index: The index of the chain to select
    """
    result = connection().send_command(
        "select_rack_chain",
        {"track_index": track_index, "device_index": device_index, "chain_index": chain_index},
    )
    if "error" in result:
        return f"Error: {result.get('error')}"
    return f"Selected chain '{result.get('chain_name')}'"


@tool
def set_device_parameter(
    track_index: int, device_index: int, parameter_index: int, value: float
) -> str:
    """
    Set a device parameter value.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    - parameter_index: The index of the parameter to set
    - value: The new value for the parameter (will be clamped to valid range)
    """
    result = connection().send_command(
        "set_device_parameter",
        {
            "track_index": track_index,
            "device_index": device_index,
            "parameter_index": parameter_index,
            "value": value,
        },
    )
    return f"Set {result.get('parameter_name')} to {result.get('value')} (range: {result.get('min')} - {result.get('max')})"


@tool
def toggle_device(track_index: int, device_index: int) -> str:
    """
    Toggle a device on or off.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    """
    result = connection().send_command(
        "toggle_device", {"track_index": track_index, "device_index": device_index}
    )
    state = "on" if result.get("is_active") else "off"
    return f"Toggled device '{result.get('device_name')}' {state}"
