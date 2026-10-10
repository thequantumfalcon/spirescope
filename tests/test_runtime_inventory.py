"""scripts/runtime_inventory.py: what the release SBOM says about the runtime.

Two defects this guards:
  * every runtime package went into the SPDX document as licenseDeclared
    NOASSERTION, although the license is right there in the dist-info the
    inventory step reads before metadata is stripped;
  * the vendored swagger-ui-dist version was a literal in the script, so the
    SBOM would keep reporting it after the vendored files moved on.
"""
import importlib.metadata as metadata
import importlib.util
import json
import re
from email.message import Message
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
PROVENANCE = REPO_ROOT / "sts2" / "static" / "swagger" / "provenance.json"


@pytest.fixture
def inventory_module(monkeypatch):
    # The script imports its sibling check_notices the way it is run in CI:
    # from the scripts directory.
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("runtime_inventory",
                                                  SCRIPTS / "runtime_inventory.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inventory(packages):
    return {"python": "3.14.7", "openssl": "OpenSSL 3.5.4 30 Sep 2025",
            "platform": "test", "packages": packages}


def _entry(document, name):
    [entry] = [p for p in document["packages"] if p["name"] == name]
    return entry


class TestDeclaredLicenses:

    @pytest.mark.parametrize("value, expected", [
        ("MIT", "MIT"),
        ("mit", "MIT"),
        ("BSD-3-Clause", "BSD-3-Clause"),
        ("Apache-2.0 OR MIT", "Apache-2.0 OR MIT"),
        ("BSD", "NOASSERTION"),           # a family, not an identifier
        ("MIT License", "NOASSERTION"),   # prose
        ("Copyright (c) 2024\n\nPermission is hereby granted", "NOASSERTION"),
        ("", "NOASSERTION"),
        (None, "NOASSERTION"),
    ])
    def test_only_valid_spdx_expressions_survive(self, inventory_module, value, expected):
        assert inventory_module.spdx_expression(value) == expected

    def test_license_expression_is_preferred_over_the_license_field(
            self, inventory_module, monkeypatch):
        meta = Message()
        meta["License-Expression"] = "Apache-2.0"
        meta["License"] = "MIT"
        monkeypatch.setattr(inventory_module.metadata, "metadata", lambda name: meta)
        assert inventory_module.declared_license("anything") == "Apache-2.0"

    def test_license_field_is_used_only_when_it_is_an_expression(
            self, inventory_module, monkeypatch):
        prose, spdx = Message(), Message()
        prose["License"] = "BSD License"
        spdx["License"] = "BSD-3-Clause"
        monkeypatch.setattr(inventory_module.metadata, "metadata",
                            lambda name: {"prose": prose, "spdx": spdx}[name])
        assert inventory_module.declared_license("prose") == "NOASSERTION"
        assert inventory_module.declared_license("spdx") == "BSD-3-Clause"

    def test_real_runtime_closure_yields_canonical_or_noassertion(self, inventory_module):
        """Against the installed environment, not fixtures. Also guards the
        guard: if nothing resolved, the reader would be silently broken."""
        names = inventory_module.runtime_closure(
            inventory_module.declared_runtime_requirements())
        resolved = {}
        for name in sorted(names):
            try:
                resolved[name] = inventory_module.declared_license(name)
            except metadata.PackageNotFoundError:
                continue
        assert resolved, "no runtime package is installed here"
        for name, value in resolved.items():
            assert value == "NOASSERTION" or value == inventory_module.spdx_expression(value), name
        assert any(v != "NOASSERTION" for v in resolved.values()), (
            f"no runtime package yielded a license: {resolved}")

    def test_enrich_carries_the_inventory_license_into_spdx(self, inventory_module):
        inventory = _inventory([
            {"name": "fastapi", "version": "1.0", "license": "MIT", "modules": []},
            {"name": "jinja2", "version": "3.1.6", "license": "NOASSERTION", "modules": []},
            {"name": "legacy", "version": "1.0", "modules": []},  # pre-license inventory
            {"name": "weird", "version": "1.0", "license": "Not A License", "modules": []},
        ])
        document = inventory_module.enrich({"packages": []}, inventory, swagger_version="5.33.0")
        assert _entry(document, "fastapi")["licenseDeclared"] == "MIT"
        assert _entry(document, "jinja2")["licenseDeclared"] == "NOASSERTION"
        assert _entry(document, "legacy")["licenseDeclared"] == "NOASSERTION"
        assert _entry(document, "weird")["licenseDeclared"] == "NOASSERTION"
        # Concluded stays NOASSERTION: nobody here reviewed the license text.
        assert all(p["licenseConcluded"] == "NOASSERTION" for p in document["packages"])


class TestSwaggerVersionComesFromProvenance:

    def test_version_matches_the_vendored_files(self, inventory_module):
        recorded = json.loads(PROVENANCE.read_text(encoding="utf-8"))
        version = inventory_module.swagger_ui_version()
        assert version == recorded["version"]
        # The provenance URLs name the same release the version field does.
        for item in recorded["files"]:
            assert f"swagger-ui-dist@{version}/" in item["url"], item["file"]

    def test_enrich_uses_the_provenance_version(self, inventory_module, tmp_path, monkeypatch):
        provenance = tmp_path / "provenance.json"
        provenance.write_text(json.dumps({"version": "9.8.7", "files": []}), encoding="utf-8")
        monkeypatch.setattr(inventory_module, "SWAGGER_PROVENANCE", provenance)
        document = inventory_module.enrich({"packages": []}, _inventory([]))
        swagger = _entry(document, "swagger-ui-dist")
        assert swagger["versionInfo"] == "9.8.7"
        assert swagger["externalRefs"][0]["referenceLocator"] == "pkg:npm/swagger-ui-dist@9.8.7"

    def test_no_version_literal_remains_in_the_script(self):
        text = (SCRIPTS / "runtime_inventory.py").read_text(encoding="utf-8")
        assert not re.search(r'"swagger-ui-dist",\s*"version":\s*"\d', text)

    def test_unusable_provenance_fails_loudly(self, inventory_module, tmp_path):
        provenance = tmp_path / "provenance.json"
        provenance.write_text(json.dumps({"files": []}), encoding="utf-8")
        with pytest.raises(SystemExit):
            inventory_module.swagger_ui_version(provenance)
