"""Local overlay generation from the player's own game install.

The heavy lifting (template alignment, rendering) is exercised against a
real install in test_localize_against_real_game, which skips when the game
is absent — CI has no game, so the archive reader and the failure paths are
covered with a synthetic .pck built here.
"""
import json
import struct

import pytest

from sts2 import localize

# magic + pack version + engine version + (flags, file base) + dir offset
_HEADER_SIZE = 4 + 4 + 12 + 12 + 8


def _build_pck(tmp_path, files, *, magic=b"GDPC", rel_base=False):
    """Write a minimal Godot .pck containing `files` ({path: bytes}).

    With rel_base the archive stores offsets relative to a declared file
    base (the flag Godot sets for embedded packs); without it they are
    absolute file offsets.
    """
    entries, blob = [], bytearray()
    for path, payload in files.items():
        stored = len(blob) if rel_base else _HEADER_SIZE + len(blob)
        entries.append((path, stored, len(payload)))
        blob += payload
    index = bytearray()
    index += struct.pack("<I", len(entries))
    for path, offset, size in entries:
        raw = path.encode("utf-8")
        pad = (-len(raw)) % 4                      # Godot pads paths to 4 bytes
        index += struct.pack("<I", len(raw) + pad) + raw + b"\x00" * pad
        index += struct.pack("<2Q", offset, size)
        index += b"\x00" * 16                      # md5
        index += struct.pack("<I", 0)              # flags: not encrypted
    header = bytearray()
    header += magic
    header += struct.pack("<I", 2)                 # pack format version
    header += struct.pack("<3I", 4, 5, 1)          # engine version
    header += struct.pack("<IQ", 2 if rel_base else 0,
                          _HEADER_SIZE if rel_base else 0)
    header += struct.pack("<Q", _HEADER_SIZE + len(blob))  # directory offset
    assert len(header) == _HEADER_SIZE
    pck = tmp_path / "SlayTheSpire2.pck"
    pck.write_bytes(bytes(header) + bytes(blob) + bytes(index))
    return tmp_path


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


def test_unknown_language_lists_what_is_available(tmp_path, monkeypatch):
    game = _build_pck(tmp_path, {
        "localization/eng/cards.json": _loc({"BASH.title": "Bash"}),
        "localization/jpn/cards.json": _loc({"BASH.title": "強打"}),
    })
    monkeypatch.setattr(localize, "OUT", tmp_path / "content")
    with pytest.raises(localize.LocalizeError) as exc:
        localize.run(langs=["klingon"], game_dir=game)
    assert "klingon" in str(exc.value) and "ja" in str(exc.value)


@pytest.mark.skipif(
    not (localize.GAME_INSTALL_DIR / "SlayTheSpire2.pck").exists(),
    reason="Slay the Spire 2 is not installed on this machine")
def test_localize_against_real_game(tmp_path, monkeypatch):
    """End to end against a real install: the overlay must be loadable, carry
    its app locale code, and contain no unrendered game markup."""
    import re

    monkeypatch.setattr(localize, "OUT", tmp_path / "content")
    langs = localize.available_languages()
    assert langs, "install exposes no translatable languages"
    target = "ja" if "ja" in langs else langs[0]

    written = localize.run(langs=[target])
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
