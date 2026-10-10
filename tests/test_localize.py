"""Local overlay generation from the player's own game install.

The heavy lifting (template alignment, rendering) is exercised against a
real install in test_localize_against_real_game, which skips when the game
is absent — CI has no game, so the archive reader and the failure paths are
covered with a synthetic .pck built by tests/_pck_builder.py.
"""
import json
import os
import struct
from pathlib import Path

import pytest

from sts2 import localize
from tests._pck_builder import _HEADER_SIZE, _build_pck


def _loc(payload):
    return json.dumps(payload).encode("utf-8")


def test_reads_only_localization_json_from_the_archive(tmp_path):
    game = _build_pck(tmp_path, {
        "localization/eng/cards.json": _loc({"BASH.title": "Bash"}),
        "localization/deu/cards.json": _loc({"BASH.title": "Schmettern"}),
        "localization/deu/enchantments.json": _loc({"X.title": "Y"}),
        "localization/deu/unrelated.json": _loc({"nope": 1}),
        "art/sprites/bash.png": b"\x89PNG not json",
        "src/Core/Whatever.cs": b"x",
    })
    data = localize.read_localization(game)
    assert data["eng"]["cards"]["BASH.title"] == "Bash"
    assert data["deu"]["cards"]["BASH.title"] == "Schmettern"
    assert "enchantments" in data["deu"]
    # only the tables the builder needs, nothing else from the archive
    assert "unrelated" not in data["deu"]
    assert set(data) == {"eng", "deu"}


def test_available_languages_maps_game_folders_to_app_codes(tmp_path):
    game = _build_pck(tmp_path, {
        "localization/eng/cards.json": _loc({"BASH.title": "Bash"}),
        "localization/jpn/cards.json": _loc({"BASH.title": "強打"}),
        "localization/ptb/cards.json": _loc({"BASH.title": "Pancada"}),
        # a folder with no card table cannot produce an overlay
        "localization/kor/enchantments.json": _loc({"X.title": "Y"}),
    })
    assert localize.available_languages(game) == ["ja", "pt"]


def test_missing_or_wrong_archive_is_reported_not_raised_raw(tmp_path):
    with pytest.raises(localize.LocalizeError, match="No SlayTheSpire2.pck"):
        localize.read_localization(tmp_path / "nowhere")

    game = _build_pck(tmp_path, {"localization/eng/cards.json": _loc({})},
                      magic=b"NOPE")
    with pytest.raises(localize.LocalizeError, match="not a Godot archive"):
        localize.read_localization(game)


def test_archive_without_english_is_rejected(tmp_path):
    """Every template is aligned against English; without it nothing can be
    resolved, so fail loudly instead of writing empty overlays."""
    game = _build_pck(tmp_path, {
        "localization/deu/cards.json": _loc({"BASH.title": "Schmettern"}),
    })
    with pytest.raises(localize.LocalizeError, match="No English"):
        localize.read_localization(game)


def test_relative_file_base_offsets_are_honoured(tmp_path):
    """Godot sets a flag meaning entry offsets are relative to a base; getting
    this wrong silently reads the wrong bytes."""
    game = _build_pck(tmp_path, {
        "localization/eng/cards.json": _loc({"BASH.title": "Bash"}),
    }, rel_base=True)
    assert localize.read_localization(game)["eng"]["cards"]["BASH.title"] == "Bash"


def test_truncated_pck_is_reported_as_corrupt(tmp_path):
    """A struct.error from a short read must surface as LocalizeError, not
    an uncaught traceback."""
    game = _build_pck(tmp_path, {
        "localization/eng/cards.json": _loc({"BASH.title": "Bash"}),
    })
    pck = game / "SlayTheSpire2.pck"
    pck.write_bytes(pck.read_bytes()[:_HEADER_SIZE])  # header only, no directory
    with pytest.raises(localize.LocalizeError, match="corrupt or truncated"):
        localize.read_localization(game)


def test_implausible_directory_count_is_rejected(tmp_path):
    game = _build_pck(tmp_path, {
        "localization/eng/cards.json": _loc({"BASH.title": "Bash"}),
    })
    pck = game / "SlayTheSpire2.pck"
    raw = bytearray(pck.read_bytes())
    dir_offset, = struct.unpack("<Q", raw[32:40])
    struct.pack_into("<I", raw, dir_offset, 0xFFFFFFFF)  # absurd entry count
    pck.write_bytes(bytes(raw))
    with pytest.raises(localize.LocalizeError, match="implausible"):
        localize.read_localization(game)


def test_implausible_path_length_is_rejected(tmp_path):
    game = _build_pck(tmp_path, {
        "localization/eng/cards.json": _loc({"BASH.title": "Bash"}),
    })
    pck = game / "SlayTheSpire2.pck"
    raw = bytearray(pck.read_bytes())
    dir_offset, = struct.unpack("<Q", raw[32:40])
    struct.pack_into("<I", raw, dir_offset + 4, 0xFFFFFFF0)  # absurd plen
    pck.write_bytes(bytes(raw))
    with pytest.raises(localize.LocalizeError, match="path length"):
        localize.read_localization(game)


def test_out_of_range_entry_offset_is_rejected(tmp_path):
    game = _build_pck(tmp_path, {
        "localization/eng/cards.json": _loc({"BASH.title": "Bash"}),
    })
    pck = game / "SlayTheSpire2.pck"
    raw = bytearray(pck.read_bytes())
    dir_offset, = struct.unpack("<Q", raw[32:40])
    path = b"localization/eng/cards.json"
    pad = (-len(path)) % 4
    off_field = dir_offset + 4 + len(path) + pad
    struct.pack_into("<Q", raw, off_field, 10_000_000_000)  # way past EOF
    pck.write_bytes(bytes(raw))
    with pytest.raises(localize.LocalizeError, match="offset"):
        localize.read_localization(game)


def test_unknown_language_lists_what_is_available(tmp_path, monkeypatch):
    game = _build_pck(tmp_path, {
        "localization/eng/cards.json": _loc({"BASH.title": "Bash"}),
        "localization/jpn/cards.json": _loc({"BASH.title": "強打"}),
    })
    monkeypatch.setattr(localize, "OUT", tmp_path / "content")
    with pytest.raises(localize.LocalizeError) as exc:
        localize.run(langs=["klingon"], game_dir=game)
    assert "klingon" in str(exc.value) and "ja" in str(exc.value)


def _real_game_dir() -> Path:
    """The install this machine actually has. conftest points STS2_GAME_DIR at
    an empty directory for every other test and keeps the original setting in
    SPIRESCOPE_TEST_REAL_GAME_DIR; with neither set, detect it as the app does."""
    from sts2.config import _find_game_dir

    explicit = os.environ.get("SPIRESCOPE_TEST_REAL_GAME_DIR")
    if explicit and explicit != "detect":
        return Path(explicit)
    hidden = os.environ.pop("STS2_GAME_DIR", None)
    try:
        return _find_game_dir()
    finally:
        if hidden is not None:
            os.environ["STS2_GAME_DIR"] = hidden


_REAL_GAME_DIR = _real_game_dir()


@pytest.mark.skipif(
    not (_REAL_GAME_DIR / "SlayTheSpire2.pck").exists(),
    reason="Slay the Spire 2 is not installed on this machine")
def test_localize_against_real_game(tmp_path, monkeypatch):
    """End to end against a real install: the overlay must be loadable, carry
    its app locale code, and contain no unrendered game markup."""
    import re

    monkeypatch.setattr(localize, "OUT", tmp_path / "content")
    langs = localize.available_languages(_REAL_GAME_DIR)
    assert langs, "install exposes no translatable languages"
    target = "ja" if "ja" in langs else langs[0]

    written = localize.run(langs=[target], game_dir=_REAL_GAME_DIR)
    assert [p.name for p in written] == [f"{target}.json"]

    data = json.loads(written[0].read_text(encoding="utf-8"))
    assert data["_meta"]["code"] == target
    assert data["cards"], "no cards translated"

    residue = re.compile(r"\{[A-Za-z]+[:}]|\[/?(?:gold|blue|red|green)\]|@[A-Z][ES]\b")
    for family, entries in data.items():
        if family == "_meta":
            continue
        for eid, entry in entries.items():
            for field, value in entry.items():
                assert not residue.search(value), f"{eid}.{field}: {value!r}"


@pytest.mark.parametrize("version", ["v0.111.0", None])
def test_overlay_uses_selected_install_identity_and_handles_small_tables(tmp_path, monkeypatch, version):
    game = _build_pck(tmp_path, {
        "localization/eng/cards.json": _loc({"BASH.title":"Bash", "BASH.description":"Damage."}),
        "localization/deu/cards.json": _loc({"BASH.title":"Schlag", "BASH.description":"Schaden."}),
    })
    if version:
        (game/'release_info.json').write_text(json.dumps({"version":version, "commit":"abc12345"}))
    app = tmp_path / 'catalog'
    app.mkdir()
    for family in ('cards', 'relics', 'potions', 'enemies', 'events'):
        rows = [{'id':'CARD.BASH', 'name':'Bash', 'description':'Damage.'}] if family == 'cards' else []
        (app/f'{family}.json').write_text(json.dumps(rows))
    monkeypatch.setattr(localize, 'APP', app)
    monkeypatch.setattr(localize, 'OUT', tmp_path/'overlays')
    paths = localize.run(langs=['de'], game_dir=game)
    overlay = json.loads(paths[0].read_text(encoding='utf-8'))
    assert overlay['_meta']['game_version'] == (version or '')
    assert overlay['_meta'].get('game_commit', '') == ('abc12345' if version else '')
    assert overlay['cards']['CARD.BASH']['name'] == 'Schlag'
