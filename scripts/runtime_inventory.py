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
from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression

REPO_ROOT = Path(__file__).resolve().parent.parent
# Written when swagger-ui-dist was vendored, next to the files it describes.
SWAGGER_PROVENANCE = REPO_ROOT / "sts2" / "static" / "swagger" / "provenance.json"


def spdx_expression(value) -> str:
    """`value` as a canonical SPDX license expression, or NOASSERTION.

    NOASSERTION is SPDX's own word for "not known": an SBOM that guesses a
    license from prose or a classifier is worse than one that says it does not
    know.
    """
    if not isinstance(value, str) or not value.strip() or "\n" in value.strip():
        return "NOASSERTION"
    try:
        return str(canonicalize_license_expression(value.strip()))
    except InvalidLicenseExpression:
        return "NOASSERTION"


def declared_license(name: str) -> str:
    """The license a distribution declares, read while its dist-info exists.

    Core metadata 2.4's License-Expression is preferred. The older free-text
    License field counts only when it already parses as an SPDX expression;
    full license texts and names like "BSD" do not, and classifiers are never
    translated.
    """
    meta = metadata.metadata(name)
    for candidate in (meta.get("License-Expression"), meta.get("License")):
        expression = spdx_expression(candidate)
        if expression != "NOASSERTION":
            return expression
    return "NOASSERTION"


def swagger_ui_version(provenance: Path | None = None) -> str:
    """The vendored swagger-ui-dist version, from its provenance record."""
    provenance = provenance or SWAGGER_PROVENANCE
    version = json.loads(provenance.read_text(encoding="utf-8")).get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"{provenance} records no usable swagger-ui-dist version: {version!r}")
    return version


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
        packages.append({"name": name, "version": metadata.version(name),
                         "license": declared_license(name), "modules": evidence})
    if missing:
        raise SystemExit("Runtime dependencies missing from the build analysis: " + ", ".join(missing))
    return {"python": platform.python_version(), "platform": platform.platform(),
            "openssl": ssl.OPENSSL_VERSION, "packages": packages}


def enrich(document: dict, inventory: dict, swagger_version: str | None = None) -> dict:
    swagger_version = swagger_version or swagger_ui_version()
    packages = list(inventory["packages"]) + [{"name": "CPython", "version": inventory["python"]},
                                             {"name": "OpenSSL", "version": inventory["openssl"].split()[1]},
                                             {"name": "swagger-ui-dist", "version": swagger_version}]
    existing = {p.get("SPDXID") for p in document.get("packages", [])}
    for package in packages:
        name, version = package["name"], package["version"]
        spdx_id = "SPDXRef-runtime-" + re.sub(r"[^a-zA-Z0-9.-]", "-", name)
        if spdx_id in existing:
            continue
        entry = {"name": name, "versionInfo": version, "SPDXID": spdx_id,
                 "downloadLocation": "NOASSERTION", "filesAnalyzed": False,
                 "licenseConcluded": "NOASSERTION",
                 # From the pre-strip inventory; re-validated, so an inventory
                 # written before it carried licenses still yields NOASSERTION.
                 "licenseDeclared": spdx_expression(package.get("license")),
                 "copyrightText": "NOASSERTION"}
        if name in {"CPython", "OpenSSL"}:
            vendor, product = ("python", "python") if name == "CPython" else ("openssl", "openssl")
            entry["externalRefs"] = [{"referenceCategory": "SECURITY", "referenceType": "cpe23Type",
                "referenceLocator": f"cpe:2.3:a:{vendor}:{product}:{version}:*:*:*:*:*:*:*"}]
        else:
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
    parser.add_argument("--qualification", type=Path)
    args = parser.parse_args()
    if args.analysis:
        result = collect(args.analysis)
        args.inventory.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.spdx:
        document = json.loads(args.spdx.read_text(encoding="utf-8"))
        inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
        if args.qualification:
            runtime = json.loads(args.qualification.read_text(encoding="utf-8"))["runtime"]
            for field in ("python", "openssl"):
                if runtime[field] != inventory[field]:
                    raise SystemExit(f"Built executable {field} differs from the inventoried build runtime")
        args.spdx.write_text(json.dumps(enrich(document, inventory), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
