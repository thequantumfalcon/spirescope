"""An unreadable last_updated.txt reads as "unknown", not as a 500.

get_last_updated runs on every home page render. The data swap renames the
data directory and a scanner can hold the file open, so it can exist at the
exists() check and fail at the read.
"""
import logging

import pytest

from sts2 import knowledge
from sts2.knowledge import get_last_updated


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "DATA_DIR", tmp_path)
    return tmp_path


def test_a_readable_file_is_returned(data_dir):
    (data_dir / "last_updated.txt").write_text("2026-03-07T10:00:00+00:00\n", encoding="utf-8")
    assert get_last_updated() == "2026-03-07T10:00:00+00:00"


def test_a_missing_file_is_unknown(data_dir):
    assert get_last_updated() == ""


def test_a_file_that_exists_but_cannot_be_read_is_unknown(data_dir, caplog):
    # A directory passes exists() and fails read_text() with an OSError,
    # the same sequence as a file renamed or locked between the two calls.
    (data_dir / "last_updated.txt").mkdir()
    with caplog.at_level(logging.DEBUG, logger="sts2.knowledge"):
        assert get_last_updated() == ""
    assert "last_updated.txt" in caplog.text


def test_a_file_that_is_not_text_is_unknown(data_dir):
    (data_dir / "last_updated.txt").write_bytes(b"\xff\xfe\xfa not utf-8")
    assert get_last_updated() == ""


async def test_the_home_page_renders_when_the_file_cannot_be_read(client, data_dir):
    (data_dir / "last_updated.txt").mkdir()
    resp = await client.get("/")
    assert resp.status_code == 200
