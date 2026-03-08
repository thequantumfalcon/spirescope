# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Spirescope."""

import os

a = Analysis(
    ['sts2/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('sts2/data', 'sts2/data'),
        ('sts2/templates', 'sts2/templates'),
        ('sts2/static', 'sts2/static'),
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
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Spirescope',
)
