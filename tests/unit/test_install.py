"""Tests for the remote-script installer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ableton_mcp import install


def test_install_writes_the_script(tmp_path: Path) -> None:
    target = tmp_path / "AbletonMCP"
    dest = install.install(target_dir=target)

    assert dest == target / "__init__.py"
    assert dest.is_file()
    # It should be the real remote script, not an empty file.
    assert len(dest.read_text()) > 1000


def test_install_creates_missing_directories(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "AbletonMCP"
    install.install(target_dir=target)

    assert target.is_dir()


def test_install_clears_stale_bytecode(tmp_path: Path) -> None:
    target = tmp_path / "AbletonMCP"
    target.mkdir()
    stale = target / "__pycache__"
    stale.mkdir()
    (stale / "old.pyc").write_bytes(b"stale")

    install.install(target_dir=target)

    assert not stale.exists()


def test_install_raises_when_ableton_is_missing(tmp_path: Path) -> None:
    with patch.object(install, "find_remote_scripts_dir", return_value=None):
        with pytest.raises(FileNotFoundError, match="user library"):
            install.install()


def test_candidates_are_platform_specific() -> None:
    with patch("platform.system", return_value="Darwin"):
        assert "Music" in str(install.user_library_candidates()[0])
    with patch("platform.system", return_value="Windows"):
        assert "Documents" in str(install.user_library_candidates()[0])


def test_main_reports_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with patch.object(install, "find_remote_scripts_dir", return_value=tmp_path):
        code = install.main()

    assert code == 0
    out = capsys.readouterr().out
    assert "Control Surface" in out
    assert "9877" in out


def test_main_reports_failure_when_ableton_missing(capsys: pytest.CaptureFixture[str]) -> None:
    with patch.object(install, "find_remote_scripts_dir", return_value=None):
        code = install.main()

    assert code == 1
    assert "error" in capsys.readouterr().err
