# Download verification and security warnings

Spirescope's desktop distribution is an unsigned PyInstaller application.
A warning can concern reputation, publisher identity, unwanted software or a
malware detection. We cannot determine its cause from the packaging format or
declare every detection a false positive. Microsoft's [SmartScreen overview](https://learn.microsoft.com/en-us/windows/security/operating-system-security/virus-and-threat-protection/microsoft-defender-smartscreen/)
explains its reputation and threat checks.

## Verify the exact download

Download from this repository's GitHub Releases page. Compare the archive with
the adjacent SHA-256 file. On Windows:

```powershell
Get-FileHash .\Spirescope-windows.zip -Algorithm SHA256
```

On macOS:

```bash
shasum -a 256 -c Spirescope-macos.zip.sha256
```

With GitHub CLI, verify the provenance of the same archive:

```bash
gh attestation verify Spirescope-windows.zip --repo thequantumfalcon/spirescope
```

Inspect the reported source commit, repository, workflow and subject digest.
A checksum establishes byte equality and provenance identifies the build; neither
proves the absence of malicious behavior or substitutes for a publisher signature.

## Investigate a warning

Keep the release version, archive digest, detection name and security-product
version. Report these in an issue without private paths or user data. If the
download or provenance does not match, do not run it. A matching file with a
detection still needs investigation. Do not disable protection or add a broad
folder exclusion as a routine installation step.

Microsoft accepts suspected incorrect detections through its
[file-submission service](https://www.microsoft.com/en-us/wdsi/filesubmission).
Select the product that issued the warning. Vendor review results and turnaround
are outside this project's control. A scanner vote count alone does not establish
whether a file is safe.

## Source installation

You can inspect and run the source in a separate Python environment. This avoids
the frozen executable but still requires trust in the source and its dependencies.

```bash
git clone https://github.com/thequantumfalcon/spirescope.git
cd spirescope
python -m venv .venv
```

Activate `.venv\Scripts\activate` on Windows or `source .venv/bin/activate` on
macOS/Linux, then install and start:

```bash
pip install --require-hashes -r requirements-runtime-lock.txt
pip install . --no-deps
spirescope
```

See [SUPPORT.md](SUPPORT.md) for tested Python versions, data/state recovery and
what information helps reproduce a problem.

## macOS and signing status

The current workflow does not apply an Apple Developer ID signature or submit
the app for notarization. Gatekeeper may block a downloaded build. Verify the
archive and consult the warning's details before deciding whether to trust it;
the word "damaged" is not by itself proof of a harmless quarantine flag.

Windows Authenticode signing and Apple notarization require separate eligible
maintainer credentials. No signing integration is claimed until an actual
distributed artifact verifies. Signing identifies a publisher and does not
guarantee every security product will accept a build. See the release's runtime
inventory, SBOM and qualification evidence alongside its provenance.
