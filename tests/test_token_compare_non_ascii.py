"""A non-ASCII configured token must not turn requests into 500s.

tokens_equal checked only the provided value for ASCII, and
secrets.compare_digest raises TypeError on a non-ASCII str. With
STS2_AUTH_TOKEN or SPIRESCOPE_ADMIN_TOKEN set to a non-ASCII value, every
request on a network bind therefore failed with a 500.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from sts2.app import app, tokens_equal

TOKEN = "pässwörd-für-das-lan"


@pytest.mark.parametrize("provided, expected", [
    ("ascii-token", TOKEN),
    (TOKEN, "ascii-token"),
    (TOKEN + "x", TOKEN),
    (TOKEN, TOKEN + "x"),
])
def test_non_ascii_on_either_side_compares_without_raising(provided, expected):
    assert tokens_equal(provided, expected) is False


def test_a_non_ascii_token_matches_itself():
    assert tokens_equal(TOKEN, TOKEN) is True


def test_an_undecodable_environment_value_does_not_raise():
    # POSIX decodes undecodable environment bytes to lone surrogates.
    assert tokens_equal("ascii-token", "token-\udcff") is False
    assert tokens_equal("token-\udcff", "token-\udcff") is True


def _client(**headers):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                       headers=headers)


async def test_a_wrong_token_against_a_non_ascii_one_is_a_401(monkeypatch):
    monkeypatch.setenv("STS2_AUTH_TOKEN", TOKEN)
    async with _client(**{"X-Auth-Token": "test-auth-token"}) as client:
        resp = await client.get("/cards")
    assert resp.status_code == 401


async def test_a_non_ascii_token_signs_in(monkeypatch):
    monkeypatch.setenv("STS2_AUTH_TOKEN", TOKEN)
    async with _client() as client:
        resp = await client.get("/cards", params={"token": TOKEN}, follow_redirects=False)
    assert resp.status_code == 303


async def test_a_non_ascii_admin_token_rejects_a_wrong_one_with_403(monkeypatch):
    import sts2.app as app_module
    monkeypatch.setattr(app_module, "_ADMIN_TOKEN", TOKEN)
    async with _client(**{"X-Auth-Token": "test-auth-token",
                          "X-Admin-Token": "test-admin-token"}) as client:
        resp = await client.post("/api/reset/stats")
    assert resp.status_code == 403
