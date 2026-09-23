"""Read installed release identity without executing the game or inferring a branch."""
import hashlib
import json
from pathlib import Path

_MAX_RELEASE_BYTES = 64 * 1024


def read_game_release(game_dir: Path) -> dict[str, str]:
    """Return only bounded public build identifiers; absent metadata stays unknown.

    The game's branch string may itself be a version/tag. Do not reinterpret it
    as Steam's main/beta branch, or equate a game commit with a Steam build ID.
    Invalid or missing metadata must not prevent reading a valid game archive.
    """
    try:
        with (game_dir / "release_info.json").open("rb") as handle:
            raw = handle.read(_MAX_RELEASE_BYTES + 1)
        if len(raw) > _MAX_RELEASE_BYTES:
            return {}
        data = json.loads(raw)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    result = {f"game_{key}": value for key in ("version", "commit", "branch")
              if isinstance(value := data.get(key), str) and value
              and len(value) <= 128 and value.isprintable()}
    if result:
        result["release_info_sha256"] = hashlib.sha256(raw).hexdigest()
    return result
