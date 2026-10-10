"""CLI text that has to match what the app actually does."""
import os
import sys
from unittest.mock import patch

from sts2.__main__ import main


def test_update_names_its_primary_source(capsys):
    """slaythespire2.gg is the primary source; the wiki only fills gaps
    (docs/DATA_SOURCES.md)."""
    with patch.object(sys, "argv", ["sts2", "--help"]):
        main()
    out = capsys.readouterr().out
    update_line = next(line for line in out.splitlines() if line.strip().startswith("update "))
    assert "slaythespire2.gg" in update_line


def test_network_bind_banner_states_how_long_a_sign_in_lasts(capsys):
    from sts2.app import _AUTH_TICKET_MAX_AGE
    assert _AUTH_TICKET_MAX_AGE == 7 * 24 * 3600, "update the banner text with the constant"
    with patch.object(sys, "argv", ["sts2", "serve", "--no-browser"]), \
         patch("sts2.config.HOST", "0.0.0.0"), \
         patch.dict(os.environ, {"STS2_AUTH_TOKEN": "s3cret"}), \
         patch("uvicorn.run"):
        main()
    out = capsys.readouterr().out
    assert "once per browser" not in out
    assert "signed in" in out and "for a week" in out
