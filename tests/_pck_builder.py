"""Synthetic Godot .pck archives for the tests that read one.

Shared by test_localize.py and test_game_content_audit.py. It lives in its own
module, not in either test file, so that neither test module is imported by
the other as a helper library.
"""
import struct

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
