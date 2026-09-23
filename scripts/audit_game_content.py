"""Read-only installed-game inventory; no game execution or application imports.

Run from a source checkout. Output contains identifiers and hashes, not game text.
Localization entries can be unused, deprecated, or test fixtures: this report is
an investigation queue, never a certificate of playable-content completeness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

MAX_TABLE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
# native table: (catalog filename, accepted catalog namespaces, name suffix)
FAMILIES = {
    "cards": ("cards", ("CARD",), "title"),
    "relics": ("relics", ("RELIC",), "title"),
    "potions": ("potions", ("POTION",), "title"),
    "monsters": ("enemies", ("MONSTER", "BOSS"), "name"),
    "encounters": ("enemies", ("ENCOUNTER",), "title"),
    "events": ("events", ("EVENT",), "title"),
    "ancients": ("events", ("EVENT",), "title"),
    "epochs": ("epochs", (), "title"),
    "badges": ("badges", ("BADGE",), "badge"),
    **{name: (None, (), "title") for name in (
        "characters", "acts", "afflictions", "enchantments", "powers",
        "orbs", "card_keywords", "static_hover_tips", "intents",
        "modifiers", "game_modes", "ascension", "achievements",
    )},
}
FIELDS = {
    "cards": ("description", "description_upgraded", "branch"),
    "relics": ("description", "branch"),
    "potions": ("description", "branch"),
    "enemies": ("hp_range", "patterns", "act"),
    "events": ("description", "choices"),
    "epochs": ("requirement", "unlocks"),
    "badges": ("requirement",),
}


def read_pack(pack: Path) -> tuple[dict, dict, list[str]]:
    """Read bounded English JSON tables from the game's indexed Godot pack."""
    total_size = pack.stat().st_size
    tables, hashes, languages = {}, {}, set()
    with pack.open("rb") as handle:
        def unpack(fmt):
            size = struct.calcsize(fmt)
            raw = handle.read(size)
            if len(raw) != size:
                raise ValueError("Truncated pack index")
            return struct.unpack(fmt, raw)

        if handle.read(4) != b"GDPC":
            raise ValueError("Not a Godot pack")
        version, = unpack("<I")
        if version not in (2, 3):
            raise ValueError(f"Unsupported pack format {version}")
        unpack("<3I")  # engine version
        flags, base = unpack("<IQ")
        if flags & 1:
            raise ValueError("Encrypted pack directory is unsupported")
        directory, = unpack("<Q")
        if directory < 40 or directory > total_size - 4:
            raise ValueError("Invalid pack directory offset")
        handle.seek(directory)
        count, = unpack("<I")
        if count > min(500_000, (total_size - handle.tell()) // 40):
            raise ValueError("Implausible pack entry count")
        selected = {}
        total = 0
        for _ in range(count):
            length, = unpack("<I")
            if not 0 < length <= 4096:
                raise ValueError("Invalid pack path length")
            raw = handle.read(length)
            if len(raw) != length:
                raise ValueError("Truncated pack path")
            name = raw.rstrip(b"\0").decode("utf-8")
            offset, size = unpack("<2Q")
            unpack("<16s")  # stored MD5 is not a provenance assertion
            entry_flags, = unpack("<I")
            parts = name.split("/")
            if len(parts) != 3 or parts[0] != "localization" or not parts[2].endswith(".json"):
                continue
            languages.add(parts[1])
            if parts[1] != "eng":
                continue
            if entry_flags & 1:
                raise ValueError("Encrypted English localization is unsupported")
            real = base + offset if flags & 2 else offset
            if real > total_size or size > total_size - real:
                raise ValueError("Localization offset is outside pack")
            total += size
            if size > MAX_TABLE_BYTES or total > MAX_TOTAL_BYTES:
                raise ValueError("Localization exceeds audit size limit")
            table = parts[2][:-5]
            if table in selected:
                raise ValueError("Duplicate English localization table")
            selected[table] = (real, size)
        for table, (offset, size) in selected.items():
            handle.seek(offset)
            raw = handle.read(size)
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict) or any(not isinstance(v, str) for v in data.values()):
                raise ValueError(f"Invalid localization table: {table}")
            tables[table] = data
            hashes[table] = hashlib.sha256(raw).hexdigest()
    if not tables.get("cards"):
        raise ValueError("No English card localization found")
    return tables, hashes, sorted(languages)


def native_ids(table: dict, suffix: str, *, variants: bool = False) -> dict[str, str]:
    if suffix == "badge":
        return {key.split(".", 1)[0]: value for key, value in table.items()
                if re.fullmatch(r"[A-Z0-9_]+\.(?:title|bronzeTitle|silverTitle|goldTitle)", key)}
    # Nested option/move titles are not entities. Uppercase dotted variants
    # (e.g. SEA_GLASS.DEFECT) are distinct localization variants. They are
    # retained for review, not treated as separate serialized ModelIds.
    identifier = r"[A-Z0-9_]+(?:\.[A-Z0-9_]+)*" if variants else r"[A-Z0-9_]+"
    pattern = rf"({identifier})\.{suffix}"
    return {match[1]: value for key, value in table.items()
            if (match := re.fullmatch(pattern, key))}


def excluded_reason(identifier: str, title: str) -> str:
    if identifier.startswith(("MOCK_", "DEPRECATED_")):
        return "explicit mock/deprecated identifier"
    if "TODO" in title.upper():
        return "placeholder title; availability requires review"
    if identifier in {"ERROR", "PROCEED", "LOCKED", "RANDOM_CHARACTER", "EMPTY_SLOT"}:
        return "interface/helper entry"
    return ""


def possible_aliases(family: str, identifier: str, ids: set[str]) -> list[str]:
    """Candidates only: never silently count name/suffix matches as coverage."""
    candidates = set()
    if family == "cards":
        candidates.update(identifier + suffix for suffix in ("_EVENT", "_QUEST", "_TOKEN"))
    if family == "relics":
        candidates.add("THE_" + identifier)
        if identifier.startswith("FAKE_"):
            candidates.update((identifier[5:] + "_FAKE", "THE_" + identifier[5:] + "_FAKE"))
    if family == "potions":
        candidates.add(identifier + "_EXTRACT")
    return sorted(candidates & ids)


def compare(tables: dict, catalogs: dict) -> dict:
    result = {}
    for family, (filename, namespaces, suffix) in FAMILIES.items():
        native = native_ids(tables.get(family, {}), suffix, variants=family == "relics")
        excluded = {key: reason for key, title in native.items()
                    if (reason := excluded_reason(key, title))}
        variants = {key: key.split(".", 1)[0] for key in native if "." in key}
        candidates = set(native) - excluded.keys() - variants.keys()
        records = catalogs.get(filename, []) if filename else []
        ids = {}
        for record in records:
            full = record["id"]
            prefix, sep, rest = full.partition(".")
            if not namespaces:
                ids[full] = full
            elif sep and prefix in namespaces:
                ids[rest] = full
        matched = candidates & ids.keys()
        unmatched = candidates - ids.keys()
        aliases = {key: possible_aliases(family, key, set(ids)) for key in sorted(unmatched)}
        aliases = {key: values for key, values in aliases.items() if values}
        result[family] = {
            "table_present": family in tables,
            "catalog": filename,
            "native_named_entries": len(native),
            "localization_variants_not_model_ids": variants,
            "excluded_entries": excluded,
            "candidate_entries": len(candidates),
            "catalog_records_in_namespace": len(ids),
            "exact_id_matches": len(matched),
            "unmatched_native_ids": sorted(unmatched),
            "possible_aliases_needing_runtime_verification": aliases,
            "catalog_ids_without_native_entry": sorted(ids.keys() - native.keys()),
            "status": "review_required" if filename else "no_dedicated_catalog; inspect feature support",
        }
    return result


def audit(game_dir: Path, data_dir: Path) -> dict:
    release_path = game_dir / "release_info.json"
    if release_path.stat().st_size > 64 * 1024:
        raise ValueError("Release metadata exceeds audit limit")
    raw_release = release_path.read_bytes()
    release = json.loads(raw_release)
    if not isinstance(release, dict):
        raise ValueError("Release metadata must be an object")
    tables, hashes, languages = read_pack(game_dir / "SlayTheSpire2.pck")
    catalogs, data_hashes = {}, {}
    for name in FIELDS:
        catalog_path = data_dir / f"{name}.json"
        if catalog_path.stat().st_size > MAX_TABLE_BYTES:
            raise ValueError("Catalog exceeds audit limit")
        raw = catalog_path.read_bytes()
        records = json.loads(raw)
        if not isinstance(records, list) or any(not isinstance(r, dict) or not isinstance(r.get("id"), str) for r in records):
            raise ValueError(f"Invalid catalog: {name}")
        if len({r["id"] for r in records}) != len(records):
            raise ValueError(f"Duplicate catalog IDs: {name}")
        catalogs[name] = records
        data_hashes[name] = hashlib.sha256(raw).hexdigest()
    return {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "game_release": {key: release.get(key) for key in ("version", "branch", "commit", "date")},
        "release_info_sha256": hashlib.sha256(raw_release).hexdigest(),
        "native_english_table_sha256": hashes,
        "native_languages": languages,
        "catalog_sha256": data_hashes,
        "families": compare(tables, catalogs),
        "catalog_fields": {
            name: {"records": len(records),
                   "empty_fields": {field: sum(not r.get(field) for r in records) for field in FIELDS[name]},
                   "declared_branches": dict(Counter(r.get("branch") or "unknown" for r in records))}
            for name, records in catalogs.items()
        },
        "complete": False,
        "limitations": [
            "Localization identifiers do not prove active pool membership or complete gameplay content.",
            "Exact ID matches do not verify field values, upgrades, effects, or runtime lookup.",
            "Alias candidates are not counted as exact matches and require an explicit runtime check.",
            "Empty fields can be intentional; no dedicated catalog does not mean absent feature support.",
            "This installed build does not certify another branch, newer build, or modded content.",
            "No game code, saves, network requests, or application initialization were executed.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", required=True, type=Path)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        output = args.output.resolve()
        for protected in (args.game_dir.resolve(), args.data_dir.resolve()):
            if output == protected or protected in output.parents:
                raise ValueError("Audit output must be outside game and catalog directories")
        report = audit(args.game_dir, args.data_dir)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Audit failed: {exc}\n")
    print(f"Wrote {output}; game {report['game_release']['version']}; completeness remains unverified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
