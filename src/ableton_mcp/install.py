"""Install the remote script into Ableton's user library.

Copying a file into a path with spaces, in a location most people have never
opened, is where non-programmers give up. This does it for them:

    uvx --from ableton-ai install-remote-script
"""

from __future__ import annotations

import platform
import shutil
import sys
from importlib import resources
from pathlib import Path

#: Ableton looks for control surfaces in a folder named after the script.
SCRIPT_DIR_NAME = "AbletonMCP"


def user_library_candidates() -> list[Path]:
    """Where Ableton keeps the user library, most likely first.

    The location is not configurable through any file we can read, so we check
    the standard spots for the platform.
    """
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        return [home / "Music" / "Ableton" / "User Library"]
    if system == "Windows":
        return [home / "Documents" / "Ableton" / "User Library"]
    # Live does not run natively on Linux, but people run it under Wine.
    return [home / "Documents" / "Ableton" / "User Library"]


def find_remote_scripts_dir() -> Path | None:
    """Return the Remote Scripts folder if the user library exists."""
    for lib in user_library_candidates():
        if lib.is_dir():
            return lib / "Remote Scripts"
    return None


def _bundled_script() -> str:
    """The remote script text.

    In an installed wheel it is bundled as package data. Running from a source
    checkout, that data is not there, so fall back to the canonical copy at the
    repo root. This keeps the installer working in both cases.
    """
    bundled = resources.files("ableton_mcp") / "_remote_script" / "__init__.py"
    if bundled.is_file():
        return bundled.read_text(encoding="utf-8")

    repo_copy = Path(__file__).resolve().parents[2] / "AbletonMCP_Remote_Script" / "__init__.py"
    if repo_copy.is_file():
        return repo_copy.read_text(encoding="utf-8")

    raise FileNotFoundError("Could not locate the bundled remote script")


def install(target_dir: Path | None = None) -> Path:
    """Copy the remote script into place. Returns where it landed."""
    if target_dir is None:
        remote_scripts = find_remote_scripts_dir()
        if remote_scripts is None:
            raise FileNotFoundError(
                "Could not find Ableton's user library. Is Live installed? "
                "Looked in: " + ", ".join(str(p) for p in user_library_candidates())
            )
        target_dir = remote_scripts / SCRIPT_DIR_NAME

    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / "__init__.py"
    destination.write_text(_bundled_script(), encoding="utf-8")

    # Live caches compiled bytecode; a stale .pyc would shadow the update.
    pycache = target_dir / "__pycache__"
    if pycache.exists():
        shutil.rmtree(pycache, ignore_errors=True)

    return destination


def main() -> int:
    try:
        destination = install()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Installed the remote script to:\n  {destination}\n")
    print("Now turn it on in Ableton:")
    print("  1. Settings, then Link, Tempo & MIDI")
    print("  2. Under Control Surface, choose AbletonMCP")
    print("  3. Leave Input and Output on None")
    print("\nLive's status bar should read: AbletonMCP: Listening for commands on port 9877")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
