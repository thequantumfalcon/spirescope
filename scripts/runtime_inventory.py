"""Inventory bundled Python modules before metadata stripping; enrich a native SPDX scan."""
import argparse
import ast
import importlib.metadata as metadata
import json
import platform
import re
import ssl
from pathlib import Path

from check_notices import declared_runtime_requirements, runtime_closure


def collect(analysis: Path) -> dict:
    toc = ast.literal_eval(analysis.read_text(encoding="utf-8"))
    modules = set()

    def walk(value):
        if isinstance(value, (list, tuple)):
            if len(value) >= 3 and isinstance(value[0], str) and value[-1] in ("PYMODULE", "PYMODULE-1", "PYMODULE-2", "EXTENSION"):
                modules.add(value[0].replace("/", ".").replace("\\", "."))
            for item in value:
                walk(item)

    walk(toc)
    mapping = metadata.packages_distributions()
    packages = []
    missing = []
    for name in sorted(runtime_closure(declared_runtime_requirements())):
        def norm(value):
            return re.sub(r"[-_.]+", "-", value).lower()
        roots = [module for module, names in mapping.items() if any(norm(n) == norm(name) for n in names)]
        evidence = sorted(m for m in modules if any(m == top or m.startswith(top + ".") for top in roots))
        if not evidence:
            missing.append(name)
        packages.append({"name": name, "version": metadata.version(name), "modules": evidence})
    if missing:
        raise SystemExit("Runtime dependencies missing from the build analysis: " + ", ".join(missing))
    return {"python": platform.python_version(), "platform": platform.platform(),
            "openssl": ssl.OPENSSL_VERSION, "packages": packages}


def enrich(document: dict, inventory: dict) -> dict:
    packages = list(inventory["packages"]) + [{"name": "CPython", "version": inventory["python"]},
                                             {"name": "swagger-ui-dist", "version": "5.33.0"}]
    existing = {p.get("SPDXID") for p in document.get("packages", [])}
    for package in packages:
        name, version = package["name"], package["version"]
        spdx_id = "SPDXRef-runtime-" + re.sub(r"[^a-zA-Z0-9.-]", "-", name)
        if spdx_id in existing:
            continue
        entry = {"name": name, "versionInfo": version, "SPDXID": spdx_id,
                 "downloadLocation": "NOASSERTION", "filesAnalyzed": False,
                 "licenseConcluded": "NOASSERTION", "licenseDeclared": "NOASSERTION",
                 "copyrightText": "NOASSERTION"}
        if name != "CPython":
            kind = "npm" if name == "swagger-ui-dist" else "pypi"
            entry["externalRefs"] = [{"referenceCategory": "PACKAGE-MANAGER",
                                      "referenceType": "purl", "referenceLocator": f"pkg:{kind}/{name}@{version}"}]
        document.setdefault("packages", []).append(entry)
        document.setdefault("relationships", []).append({"spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES", "relatedSpdxElement": spdx_id})
    required = {p["name"] for p in packages}
    assert required <= {p["name"] for p in document["packages"]}
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--spdx", type=Path)
    args = parser.parse_args()
    if args.analysis:
        result = collect(args.analysis)
        args.inventory.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.spdx:
        document = json.loads(args.spdx.read_text(encoding="utf-8"))
        inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
        args.spdx.write_text(json.dumps(enrich(document, inventory), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
