"""Static asset links resolve and carry a cache-busting version.

/static responses are cached for an hour, so a script linked without ?v=
keeps serving the old copy after an update. nav.js, overlay.js and the API
docs assets were linked bare, and the API docs page pointed its icon at a
logo.svg that was never shipped and hard-coded lang="en".
"""
import re


def _versioned(html, path):
    match = re.search(re.escape(path) + r'\?v=([^"&]+)"', html)
    assert match, f"{path} is linked without a ?v= version"
    return match.group(1)


async def test_nav_script_is_versioned(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    _versioned(resp.text, "/static/nav.js")
    assert 'src="/static/nav.js"' not in resp.text


async def test_overlay_script_is_versioned(client):
    resp = await client.get("/overlay")
    assert resp.status_code == 200
    _versioned(resp.text, "/static/overlay.js")


async def test_api_docs_assets_are_versioned(client):
    resp = await client.get("/docs")
    assert resp.status_code == 200
    for path in ("/static/swagger/swagger-ui.css", "/static/swagger/swagger-ui-bundle.js",
                 "/static/swagger/init.js"):
        _versioned(resp.text, path)


async def test_api_docs_icon_exists(client):
    resp = await client.get("/docs")
    assert resp.status_code == 200
    icon = re.search(r'<link rel="icon"[^>]*href="([^"]+)"', resp.text)
    assert icon
    assert "logo.svg" not in resp.text
    asset = await client.get(icon.group(1))
    assert asset.status_code == 200


async def test_api_docs_lang_follows_the_ui_language(client, monkeypatch):
    monkeypatch.setenv("STS2_LANG", "de")
    resp = await client.get("/docs")
    assert resp.status_code == 200
    assert '<html lang="de"' in resp.text


async def test_every_static_reference_in_the_pages_exists(client):
    """Each /static/... URL on these pages is served (no 404 assets)."""
    seen = set()
    for page in ("/", "/docs", "/overlay", "/runs", "/deck", "/analytics", "/live"):
        resp = await client.get(page)
        assert resp.status_code == 200
        seen.update(re.findall(r'(?:src|href)="(/static/[^"?]+)', resp.text))
    assert seen
    for url in sorted(seen):
        asset = await client.get(url)
        assert asset.status_code == 200, url


async def test_versions_follow_the_file_contents(client):
    """The version is the file's own content hash, like the other scripts, so
    an edit busts the cache even within one release."""
    import hashlib

    from sts2.config import STATIC_DIR

    pages = {"/": ["/static/nav.js"], "/overlay": ["/static/overlay.js"],
             "/docs": ["/static/swagger/swagger-ui.css",
                       "/static/swagger/swagger-ui-bundle.js",
                       "/static/swagger/init.js"]}
    for page, paths in pages.items():
        html = (await client.get(page)).text
        for path in paths:
            data = (STATIC_DIR / path.removeprefix("/static/")).read_bytes()
            expected = hashlib.md5(data, usedforsecurity=False).hexdigest()[:8]
            assert _versioned(html, path) == expected, path

