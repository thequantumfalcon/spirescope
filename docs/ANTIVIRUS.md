# "This file contains a virus" — what's actually happening

If Windows blocked `Spirescope.exe` with *"Operation did not complete
successfully because the file contains a virus or potentially unwanted
software"*, or SmartScreen warned you before it ran — this page explains
exactly why, and gives you three ways forward depending on how much you
want to trust a stranger's build.

**Short version:** SpireScope is an unsigned Python application packaged
with PyInstaller. Antivirus engines flag that *packaging format* on
reputation and heuristics, not because anything malicious was found. Every
line of source is in this repository, every release is built in public by
GitHub Actions, and every archive ships a SHA-256 checksum.

## Why it happens

PyInstaller bundles a Python interpreter plus your code into an executable
that unpacks and runs code at startup. That behavior pattern — self-
extracting, dynamically loading code, unsigned, low download count — is
also what some malware does, so heuristic scanners score it as suspicious.
It affects essentially every unsigned PyInstaller app, which is why you'll
find the same complaint across many open-source Python tools.

Two things that *would* make it worse are already avoided in this build:
UPX compression is disabled, and the app runs with a visible console
window rather than hidden.

The permanent fix is a code-signing certificate (see below); until that's
in place, the warning is expected.

## Option 1 — Verify, then allow it

1. **Check the checksum.** Every release ships a `.sha256` file next to the
   zip. On Windows PowerShell:

   ```powershell
   Get-FileHash .\Spirescope-windows.zip -Algorithm SHA256
   ```

   Compare with the contents of `Spirescope-windows.zip.sha256`. If they
   match, the file you downloaded is bit-for-bit what CI published.

2. **Allow the file** in Windows Security → Virus & threat protection →
   Protection history → find the item → Actions → Allow. Or add the
   SpireScope folder under Manage settings → Exclusions.

3. If SmartScreen blocks launch instead, click **More info → Run anyway**.

## Option 2 — Run from source (no executable at all)

The most cautious path, and it takes two minutes. Nothing is packaged,
so there's nothing for a heuristic scanner to object to:

```bash
git clone https://github.com/thequantumfalcon/spirescope.git
cd spirescope
python -m venv .venv && .venv\Scripts\activate    # macOS/Linux: source .venv/bin/activate
pip install -e .
spirescope
```

Then open <http://127.0.0.1:8000>. Requires Python 3.11 or newer.

## Option 3 — Wait for signed builds

Code signing is the only thing that removes these warnings permanently.
It's a paid certificate; see the maintainer note below for status.

## How to satisfy yourself it's safe

- **Read the source** — it's all here, ~700 automated tests included.
- **Check what it does on the network:** nothing, unless you ask it to.
  The server binds to `127.0.0.1` only. The sole outbound calls are the
  optional update check and the game-data refresh, both disableable with
  `SPIRESCOPE_CHECK_UPDATES=0`.
- **Check what it touches on disk:** it reads your STS2 save files and
  never writes to them.
- **Scan it yourself** — upload the zip to [VirusTotal](https://www.virustotal.com/).
  Expect a small number of heuristic/ML detections (names like
  `Trojan.Generic`, `ML.Attribute.HighConfidence`, `Wacatac`) and a large
  majority of clean results. That distribution is the signature of a
  false positive on an unsigned packer, not of an actual detection.

## Reporting a false positive

If Microsoft Defender flagged it, submitting the sample genuinely helps —
they typically correct generic detections within a few days, and the fix
propagates to everyone:

<https://www.microsoft.com/en-us/wdsi/filesubmission>

Choose "Software developer", submit the zip, and note that it's an
unsigned PyInstaller build of an open-source project with the repository
URL. Other vendors have equivalent forms.

## Maintainer notes

- Builds are produced only by GitHub Actions from tagged commits in this
  repository — there is no local build step and no other upload path.
- GitHub Releases is the only official download source.
- Signing options under consideration: Azure Trusted Signing (about
  $10/month, works from GitHub Actions, requires identity verification) or
  a traditional OV/EV certificate (roughly $200–400/year). Until then,
  this page is the honest answer to the warning.
