# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Grain Scanner Windows bundle.

Run from the packaging/ directory:
    pyinstaller grain_scanner.spec --noconfirm
Output: packaging/dist/GrainScanner/
"""

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

# Locate the grain_scanner source tree relative to this spec file
SRC   = os.path.normpath(os.path.join(SPECPATH, "..", "grain_scanner"))
ENTRY = os.path.join(SPECPATH, "launcher.py")

# ── Collect data + binaries from packages with rich resource trees ────────────
st_datas,  st_bins,  st_hidden  = collect_all("streamlit")
wv_datas,  wv_bins,  wv_hidden  = collect_all("webview")
alt_datas, alt_bins, alt_hidden = collect_all("altair")
pl_datas,  pl_bins,  pl_hidden  = collect_all("plotly")
hx_datas,  hx_bins,  hx_hidden  = collect_all("httpx")
ay_datas,  ay_bins,  ay_hidden  = collect_all("anyio")

# ── Application source files bundled verbatim ─────────────────────────────────
app_datas = [
    (os.path.join(SRC, "main.py"),          "."),
    (os.path.join(SRC, "streamlit_app.py"), "."),
    (os.path.join(SRC, "app"),              "app"),
    (os.path.join(SRC, ".env.example"),     "."),
    (os.path.join(SPECPATH, "licensing.py"), "."),   # license check module
]

block_cipher = None

a = Analysis(
    [ENTRY],
    pathex=[SRC],
    binaries=st_bins + alt_bins + pl_bins + hx_bins + ay_bins + wv_bins,
    datas=app_datas + st_datas + alt_datas + pl_datas + hx_datas + ay_datas + wv_datas,
    hiddenimports=[
        # uvicorn — all transports discovered at runtime via __import__
        "uvicorn.logging",
        "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
        "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.lifespan", "uvicorn.lifespan.on",
        # starlette / fastapi
        "starlette.routing", "starlette.middleware", "starlette.staticfiles",
        # sqlalchemy async
        "sqlalchemy.dialects.sqlite", "sqlalchemy.dialects.sqlite.aiosqlite",
        "sqlalchemy.ext.asyncio",
        "greenlet", "aiosqlite",
        # pydantic v2 deprecated shims still referenced at import time
        "pydantic.deprecated.class_validators",
        "pydantic.deprecated.config",
        "pydantic.deprecated.tools",
        # cryptography + SSL (licensing)
        "cryptography", "cryptography.hazmat.primitives.asymmetric.ed25519",
        "certifi",
        # scikit-image IO plugins
        "skimage.io._plugins.pil_plugin",
        "skimage.io._plugins.imageio_plugin",
        "skimage.filters._unsharp_mask",
        # reportlab components used via string registry
        "reportlab.graphics.charts",
        "reportlab.graphics.widgets",
        # httpx / httpcore / anyio
        "httpcore", "httpcore._async", "httpcore._sync",
        # pandas
        "pandas", "pandas._libs.tslibs.np_datetime",
        # PIL
        "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont",
        # webview
        "webview", "webview.platforms.winforms",
        # misc
        "loguru", "multipart",
        *collect_submodules("scipy"),
    ] + st_hidden + alt_hidden + pl_hidden + hx_hidden + ay_hidden + wv_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter._test", "matplotlib", "IPython", "jupyter", "pytest"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GrainScanner",
    debug=False,
    strip=False,
    upx=True,
    # console=True  → shows a terminal window with live logs (handy for debugging)
    # console=False → headless; logs go to %APPDATA%\GrainScanner\logs\app.log
    console=False,
    icon=None,   # swap in: icon=r"assets\icon.ico"  when you have one
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GrainScanner",
)
