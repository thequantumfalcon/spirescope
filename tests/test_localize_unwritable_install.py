"""`localize` on an install whose package folder cannot be written.

The overlays go into sts2/locales/content inside the installed package. On a
read-only install mkdir/write_text raised PermissionError, which is not a
LocalizeError, so `python -m sts2 localize` ended in a traceback.
"""
import sys
from unittest.mock import patch

import pytest

from sts2 import localize

GAME_TEXT = {"eng": {"cards": {"BASH.title": "Bash"}},
             "deu": {"cards": {"BASH.title": "Hieb"}}}


@pytest.fixture
def unwritable_out(tmp_path, monkeypatch):
    # A folder that can never be created, whatever the platform or user: its
    # parent is a regular file.
    blocker = tmp_path / "package-file"
    blocker.write_text("x", encoding="utf-8")
    out = blocker / "content"
    monkeypatch.setattr(localize, "OUT", out)
    monkeypatch.setattr(localize, "read_localization", lambda game_dir=None: GAME_TEXT)
    return out


def test_an_uncreatable_output_folder_is_a_localize_error(unwritable_out):
    with pytest.raises(localize.LocalizeError) as exc:
        localize.run(langs=["de"], game_dir=unwritable_out.parent)
    assert str(unwritable_out) in str(exc.value)
    assert "must be writable" in str(exc.value)


def test_a_refused_overlay_write_is_a_localize_error(tmp_path, monkeypatch):
    out = tmp_path / "content"
    monkeypatch.setattr(localize, "OUT", out)
    monkeypatch.setattr(localize, "read_localization", lambda game_dir=None: GAME_TEXT)

    def refused(release=None):
        raise PermissionError(13, "Permission denied", str(out / "deu.json"))

    monkeypatch.setattr(localize, "_build_all", refused)
    with pytest.raises(localize.LocalizeError, match="Permission denied") as exc:
        localize.run(langs=["de"], game_dir=tmp_path)
    assert "deu.json" in str(exc.value)


def test_the_cli_reports_it_without_a_traceback(unwritable_out, capsys):
    from sts2.__main__ import main
    with patch.object(sys, "argv", ["sts2", "localize", "--lang", "de"]), \
         pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Could not build translations:" in out
    assert "must be writable" in out
