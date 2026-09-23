"""Upstream asset provenance must survive checkout on every supported OS."""
import hashlib
import json
from pathlib import Path


def test_swagger_assets_match_recorded_upstream_digests():
    root = Path(__file__).parents[1] / "sts2/static/swagger"
    provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
    for entry in provenance["files"]:
        assert hashlib.sha256((root / entry["file"]).read_bytes()).hexdigest() == entry["sha256"]
