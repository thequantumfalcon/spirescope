"""Side-effect-free dataset checks shared by refreshes and packaged validation."""
import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from sts2.models import Card, Enemy, Epoch, Event, Potion, Relic

FAMILIES: dict[str, type[Card] | type[Enemy] | type[Epoch] | type[Event] | type[Potion] | type[Relic]] = {"cards": Card, "relics": Relic, "potions": Potion,
            "enemies": Enemy, "events": Event, "epochs": Epoch}


def inspect_dataset(root: Path, min_cards: int = 400) -> dict:
    errors: list[str] = []
    counts: dict[str, int] = {}
    digest = hashlib.sha256()
    for family, model in FAMILIES.items():
        name = family + ".json"
        try:
            raw = (root / name).read_bytes()
            if len(raw) > 20 * 1024 * 1024:
                raise ValueError("file exceeds size limit")
            rows = json.loads(raw)
            if not isinstance(rows, list) or not rows:
                raise ValueError("required family is empty or is not a list")
            ids = set()
            for row in rows:
                record = model.model_validate(row, strict=True)
                if not record.id or record.id in ids:
                    raise ValueError("missing or duplicate identity")
                ids.add(record.id)
            counts[family] = len(rows)
            digest.update(name.encode())
            digest.update(raw)
        except (OSError, ValueError, ValidationError) as exc:
            errors.append(f"{name}: {str(exc)[:200]}")
    if counts.get("cards", 0) < min_cards:
        errors.append(f"cards.json: requires at least {min_cards} cards")
    try:
        patches = json.loads((root / "patches.json").read_bytes())
        if not isinstance(patches, list) or not patches:
            raise ValueError("patch manifest is empty or is not a list")
        seen = set()
        for patch in patches:
            key = patch.get("patch") if isinstance(patch, dict) else None
            if not isinstance(key, str) or not key or key in seen:
                raise ValueError("missing or duplicate patch identity")
            seen.add(key)
        if not (root / "last_updated.txt").read_text(encoding="utf-8").strip():
            raise ValueError("missing data timestamp")
    except (OSError, ValueError) as exc:
        errors.append(f"metadata: {str(exc)[:200]}")
    for path in sorted(root.glob("*.json")):
        if path.stem in FAMILIES:
            continue
        try:
            raw = path.read_bytes()
            if len(raw) > 20 * 1024 * 1024:
                raise ValueError("file exceeds size limit")
            json.loads(raw)
            digest.update(path.name.encode())
            digest.update(raw)
        except (OSError, ValueError) as exc:
            errors.append(f"{path.name}: {str(exc)[:200]}")
    return {"ok": not errors, "counts": counts, "errors": errors,
            "content_digest": digest.hexdigest()}


def validate_command(args: list[str]) -> int:
    """Explicit command works in Python and frozen executables, without a server."""
    import argparse
    import os
    import tempfile

    parser = argparse.ArgumentParser(prog="spirescope validate-data")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--min-cards", type=int, default=400)
    options = parser.parse_args(args)
    root = options.directory.resolve()
    result = inspect_dataset(root, options.min_cards)
    if result["ok"]:
        # No real saves, overlays, settings or game files may repair a bad
        # candidate or influence this proof of loadability.
        with tempfile.TemporaryDirectory(prefix="spirescope-validate-") as tmp:
            os.environ["STS2_DATA_DIR"] = str(root)
            for key in ("STATE_DIR", "SAVE_DIR", "GAME_DIR", "MODS_DIR", "LOG_FILE"):
                os.environ["STS2_" + key] = str(Path(tmp) / key)
            os.environ["STS2_LANG"] = "en"
            from sts2.knowledge import KnowledgeBase
            kb = KnowledgeBase()
            for family in FAMILIES:
                if not getattr(kb, family, None):
                    result["errors"].append(f"{family}: did not load")
            result["ok"] = not result["errors"]
    print(json.dumps(result))
    return 0 if result["ok"] else 1
