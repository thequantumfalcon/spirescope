"""The save-written log line is recognised whichever path separator it uses.

_RE_WROTE_SAVE required a backslash before current_run.save, so it never
matched the forward-slash paths in macOS and Linux logs, and the live view
never saw a save being written there.
"""
from pathlib import Path

import pytest

from sts2.logparser import LogTailer


@pytest.mark.parametrize("line", [
    r"[INFO] Wrote 1234 bytes to path=C:\Users\me\AppData\Roaming\SlayTheSpire2\steam"
    r"\76561198000000000\profile1\saves\current_run.save",
    r"[INFO] Wrote 54543 bytes to path=user://steam/76561198000000000/profile1\saves"
    r"\current_run_mp.save save_dir=user://steam/76561198000000000",
    "[INFO] Wrote 1234 bytes to path=/Users/me/Library/Application Support/SlayTheSpire2/"
    "steam/76561198000000000/profile1/saves/current_run.save",
    "[INFO] Wrote 1234 bytes to path=/home/me/.local/share/SlayTheSpire2/steam/"
    "76561198000000000/profile1/saves/current_run_mp.save",
    "[INFO] Wrote 54543 bytes to path=user://steam/76561198000000000/profile1/saves/"
    "current_run.save save_dir=user://steam/76561198000000000",
])
def test_a_written_save_marks_the_run_active(line):
    tailer = LogTailer(log_path=Path("/dev/null"))
    assert tailer._process_line(line) is True
    assert tailer.state.active is True


@pytest.mark.parametrize("line", [
    "[INFO] Wrote 1234 bytes to path=/home/me/saves/progress.save",
    "[INFO] Wrote 1234 bytes to path=/home/me/saves/not_current_run.save",
])
def test_other_saves_do_not(line):
    tailer = LogTailer(log_path=Path("/dev/null"))
    tailer._process_line(line)
    assert tailer.state.active is False
