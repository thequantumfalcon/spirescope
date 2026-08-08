# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Spirescope."""

import re
import sys
from pathlib import Path

# Read the version from sts2/config.py rather than restating it. Hardcoded, it
# silently fell six releases behind (2.9.7 while the app shipped 3.0.2) and
# stamped that stale number into the Windows executable's file metadata, which
# is what users see in file properties and what installers compare.
_config_src = Path(SPECPATH, "sts2", "config.py").read_text(encoding="utf-8")
_match = re.search(r'^VERSION\s*=\s*"([^"]+)"', _config_src, re.M)
if not _match:
    raise SystemExit("spirescope.spec: could not read VERSION from sts2/config.py")
VERSION = _match.group(1)

# Windows EXE version metadata (CompanyName / ProductName / FileVersion).
# The win32 import branch only loads on Windows because the underlying
# `pefile` dependency is PE/Windows-specific; the macOS/Linux release CIs
# don't need (and can't import) it.
version_info = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    VERSION_TUPLE = tuple(int(part) for part in VERSION.split(".")) + (0,)
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=VERSION_TUPLE,
            prodvers=VERSION_TUPLE,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo([
                StringTable("040904B0", [
                    StringStruct("CompanyName", "The Quantum Falcon"),
                    StringStruct("FileDescription", "Spirescope - Slay the Spire 2 companion dashboard"),
                    StringStruct("FileVersion", VERSION),
                    StringStruct("InternalName", "Spirescope"),
                    StringStruct("LegalCopyright", "Copyright (c) The Quantum Falcon"),
                    StringStruct("OriginalFilename", "Spirescope.exe"),
                    StringStruct("ProductName", "Spirescope"),
                    StringStruct("ProductVersion", VERSION),
                ]),
            ]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )

a = Analysis(
    ['sts2/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('sts2/data', 'sts2/data'),
        ('sts2/templates', 'sts2/templates'),
        ('sts2/static', 'sts2/static'),
        # UI strings only. sts2/locales/content holds translations built from
        # the user's own game install (spirescope localize) and must never be
        # bundled: it is that machine's copy of the game's text, not ours to
        # redistribute. Listed file-by-file because naming the directory
        # would sweep content/ in with it.
        *[(str(p), 'sts2/locales')
          for p in sorted(Path('sts2/locales').glob('*.json'))],
    ],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.protocols.websockets.wsproto_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'multipart',
        'multipart.multipart',
        'python_multipart',
        'python_multipart.multipart',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'numpy', 'pandas', 'scipy', 'matplotlib', 'IPython', 'pygments',
        'PIL', 'cv2', 'sklearn', 'torch', 'tensorflow', 'pytest',
        'setuptools', 'pip', 'wheel', 'pkg_resources',
        'tkinter', 'unittest', 'doctest', 'xmlrpc', 'ftplib',
        'sphinx', 'babel', 'docutils', 'lxml', 'cryptography', 'zmq',
        'myst_parser', 'rich', 'Cython', 'psutil', 'dateutil',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Spirescope',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon='sts2/static/favicon.ico',
    version=version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Spirescope',
)
