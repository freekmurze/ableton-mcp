"""Live's browser: navigating it and loading from it.

Tools are registered by the ``@tool`` decorator, which also supplies the uniform
error handling that used to be copy-pasted into every function.
"""

from __future__ import annotations

from typing import Any

from ._base import as_json, connection, tool


@tool
def browse_path(path: list[str]) -> str:
    """
    Navigate browser by path list to get items at that location.

    Parameters:
    - path: List of path components, e.g. ["Audio Effects", "EQ Eight"] or ["Sounds", "Bass"]
    """
    result = connection().send_command("browse_path", {"path": path})
    if "error" in result:
        return f"Error: {result.get('error')}. Available categories: {result.get('available_categories', [])}"
    return as_json(result)


@tool
def get_browser_items_at_path(path: str) -> str:
    """
    Get browser items at a specific path in Ableton's browser.

    Parameters:
    - path: Path in the format "category/folder/subfolder"
            where category is one of the available browser categories in Ableton
    """
    result = connection().send_command("get_browser_items_at_path", {"path": path})

    # Check if there was an error with available categories
    if "error" in result and "available_categories" in result:
        error = result.get("error", "")
        available_cats = result.get("available_categories", [])
        return f"Error: {error}\nAvailable browser categories: {', '.join(available_cats)}"

    return as_json(result)


@tool
def get_browser_tree(category_type: str = "all") -> str:
    """
    Get a hierarchical tree of browser categories from Ableton.

    Parameters:
    - category_type: Type of categories to get ('all', 'instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects')
    """
    result = connection().send_command("get_browser_tree", {"category_type": category_type})

    # Check if we got any categories
    if "available_categories" in result and len(result.get("categories", [])) == 0:
        available_cats = result.get("available_categories", [])
        return (
            f"No categories found for '{category_type}'. "
            f"Available browser categories: {', '.join(available_cats)}"
        )

    # Format the tree in a more readable way
    total_folders = result.get("total_folders", 0)
    formatted_output = f"Browser tree for '{category_type}' (showing {total_folders} folders):\n\n"

    def format_tree(item: dict[str, Any], indent: int = 0) -> str:
        output = ""
        if item:
            prefix = "  " * indent
            name = item.get("name", "Unknown")
            path = item.get("path", "")
            has_more = item.get("has_more", False)

            # Add this item
            output += f"{prefix}• {name}"
            if path:
                output += f" (path: {path})"
            if has_more:
                output += " [...]"
            output += "\n"

            # Add children
            for child in item.get("children", []):
                output += format_tree(child, indent + 1)
        return output

    # Format each category
    for category in result.get("categories", []):
        formatted_output += format_tree(category)
        formatted_output += "\n"

    return formatted_output


@tool
def load_drum_kit(track_index: int, rack_uri: str, kit_path: str) -> str:
    """
    Load a drum rack and then load a specific drum kit into it.

    Parameters:
    - track_index: The index of the track to load on
    - rack_uri: The URI of the drum rack to load (e.g., 'Drums/Drum Rack')
    - kit_path: Path to the drum kit inside the browser (e.g., 'drums/acoustic/kit1')
    """

    # Step 1: Load the drum rack
    result = connection().send_command(
        "load_browser_item", {"track_index": track_index, "item_uri": rack_uri}
    )

    if not result.get("loaded", False):
        return f"Failed to load drum rack with URI '{rack_uri}'"

    # Step 2: Get the drum kit items at the specified path
    kit_result = connection().send_command("get_browser_items_at_path", {"path": kit_path})

    if "error" in kit_result:
        return f"Loaded drum rack but failed to find drum kit: {kit_result.get('error')}"

    # Step 3: Find a loadable drum kit
    kit_items = kit_result.get("items", [])
    loadable_kits = [item for item in kit_items if item.get("is_loadable", False)]

    if not loadable_kits:
        return f"Loaded drum rack but no loadable drum kits found at '{kit_path}'"

    # Step 4: Load the first loadable kit
    kit_uri = loadable_kits[0].get("uri")
    connection().send_command(
        "load_browser_item", {"track_index": track_index, "item_uri": kit_uri}
    )

    return f"Loaded drum rack and kit '{loadable_kits[0].get('name')}' on track {track_index}"


@tool
def load_instrument_or_effect(track_index: int, uri: str) -> str:
    """
    Load an instrument or effect onto a track using its URI.

    Parameters:
    - track_index: The index of the track to load the instrument on
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
    """
    result = connection().send_command(
        "load_browser_item", {"track_index": track_index, "item_uri": uri}
    )

    # Check if the instrument was loaded successfully
    if result.get("loaded", False):
        new_devices = result.get("new_devices", [])
        if new_devices:
            return f"Loaded instrument with URI '{uri}' on track {track_index}. New devices: {', '.join(new_devices)}"
        devices = result.get("devices_after", [])
        return f"Loaded instrument with URI '{uri}' on track {track_index}. Devices on track: {', '.join(devices)}"
    return f"Failed to load instrument with URI '{uri}'"


@tool
def load_item_to_return(return_index: int, uri: str) -> str:
    """
    Load a browser item (effect) onto a return track by URI.

    Parameters:
    - return_index: The index of the return track to load the item onto
    - uri: The URI of the browser item (obtained from browse_path or search_browser)
    """
    result = connection().send_command(
        "load_browser_item_to_return", {"return_index": return_index, "item_uri": uri}
    )
    if "error" in result:
        return f"Error: {result.get('error')}"
    return f"Loaded '{result.get('item_name')}' on return track '{result.get('return_track_name')}'"


@tool
def load_item_to_track(track_index: int, uri: str) -> str:
    """
    Load a browser item (instrument or effect) onto a track by URI.

    Parameters:
    - track_index: The index of the track to load the item onto
    - uri: The URI of the browser item (obtained from browse_path or search_browser)
    """
    result = connection().send_command(
        "load_instrument_or_effect", {"track_index": track_index, "uri": uri}
    )
    if "error" in result:
        return f"Error: {result.get('error')}"
    return f"Loaded '{result.get('item_name')}' on track '{result.get('track_name')}'"


@tool
def search_browser(query: str, category: str = "all") -> str:
    """
    Search the browser for items matching a query.

    Parameters:
    - query: Search term to find in item names
    - category: Category to search in (all, instruments, sounds, drums, audio_effects, midi_effects)
    """
    result = connection().send_command("search_browser", {"query": query, "category": category})
    if "error" in result:
        return f"Error: {result.get('error')}"

    count = result.get("result_count", 0)
    if count == 0:
        return f"No results found for '{query}' in category '{category}'"

    return f"Found {count} results for '{query}':\n" + as_json(result.get("results", []))
