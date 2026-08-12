Spirescope - Slay the Spire 2 Companion Dashboard
==================================================

This file ships with both the Windows and macOS builds. Follow the section
for your platform.

--------------------------------------------------------------------------
WINDOWS
--------------------------------------------------------------------------

IF WINDOWS BLOCKED THIS FILE:

  Windows may flag Spirescope.exe as a virus. It is a false positive that
  affects unsigned Python applications packaged with PyInstaller - the
  packaging format is what gets flagged, not the contents.

  Verify the download yourself: compare the .sha256 file published beside
  the zip on the release page with
  Get-FileHash .\Spirescope-windows.zip -Algorithm SHA256

  Full explanation, plus how to allow it or run from source instead:
  https://github.com/thequantumfalcon/spirescope/blob/master/docs/ANTIVIRUS.md

HOW TO RUN:

  1. Double-click Spirescope.exe
  2. Your browser opens automatically
  3. Leave the console window open while Spirescope is running -
     closing it stops the app
     (If the browser does not open, go to http://127.0.0.1:8000 yourself)

--------------------------------------------------------------------------
macOS
--------------------------------------------------------------------------

MACOS WILL REFUSE TO OPEN THIS UNTIL YOU CLEAR THE QUARANTINE FLAG:

  This build is not signed or notarized, so Gatekeeper blocks it. You may
  see "cannot be opened because the developer cannot be verified", or "is
  damaged and can't be opened" - the download is not damaged, it just
  carries the quarantine attribute your browser attached.

  Verify the download first, then clear the attribute:

    shasum -a 256 -c Spirescope-macos.zip.sha256
    xattr -dr com.apple.quarantine Spirescope

  Only do this for software you have chosen to trust and whose checksum
  you have confirmed.

HOW TO RUN:

  1. Open Terminal in this folder
  2. Run:  ./Spirescope
  3. Your browser opens automatically
  4. Leave the terminal window open while Spirescope is running -
     closing it stops the app
     (If the browser does not open, go to http://127.0.0.1:8000 yourself)

--------------------------------------------------------------------------
BOTH PLATFORMS
--------------------------------------------------------------------------

OPTIONAL:

  - To stop the browser opening automatically, launch with --no-browser
    or set SPIRESCOPE_OPEN_BROWSER=0

FEATURES:

  - Card, relic, potion, and enemy browser
  - Deck analyzer with archetype detection
  - Live run tracker (updates in real-time)
  - Run history and analytics
  - Strategy guides for all characters

NOTES:

  - Requires Slay the Spire 2 installed on this machine for save file
    features (card/relic/enemy lookup works without it)
  - Packaged builds do not auto-check GitHub for updates by default
  - To stop the server, click the red "Stop" button in the nav bar, or
    close the console/terminal window. Closing only the browser tab leaves
    it running.
  - Your settings, community stats and saved hypotheses are stored outside
    this folder, so refreshing game data or replacing this build will not
    discard them
  - Default address: http://127.0.0.1:8000
  - To change the port, set STS2_PORT environment variable before launching
  - LICENSE.txt and THIRD_PARTY_NOTICES.md in this folder cover this build
    and the open-source components it bundles
