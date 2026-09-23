"""An overlay's release provenance must come from the selected installation."""
import hashlib
import json

import pytest

from sts2.game_version import read_game_release


def test_release_identity_keeps_distinct_game_identifiers(tmp_path):
    raw = json.dumps({'version': 'v0.111.0', 'branch': 'release/0.111',
                      'commit': 'abc12345', 'account': 'do not export'}).encode()
    (tmp_path/'release_info.json').write_bytes(raw)
    assert read_game_release(tmp_path) == {
        'game_version':'v0.111.0', 'game_branch':'release/0.111', 'game_commit':'abc12345',
        'release_info_sha256':hashlib.sha256(raw).hexdigest(),
    }


@pytest.mark.parametrize('payload', [b'not json', b'[]', b'null', b'{}', b'x'*65537,
                                   b'{"version": 123, "branch": [], "commit": null}',
                                   b'{"version": "v1\\nfalse"}'], ids=["invalid", "array", "null", "empty", "oversized", "wrong-types", "control"])
def test_invalid_identity_stays_unknown(tmp_path, payload):
    assert read_game_release(tmp_path) == {}
    (tmp_path/'release_info.json').write_bytes(payload)
    assert read_game_release(tmp_path) == {}
