"""
Pre-build import check — run this before PyInstaller to surface all missing
modules at once rather than discovering them one crash at a time.

Usage:  python packaging/preflight.py
"""
import importlib
import sys

REQUIRED = [
    # Web framework
    "fastapi", "starlette", "uvicorn", "uvicorn.main",
    # Database
    "sqlalchemy", "sqlalchemy.ext.asyncio", "aiosqlite", "greenlet",
    # Validation
    "pydantic", "pydantic_settings",
    # Image processing
    "cv2", "skimage", "scipy", "numpy", "PIL",
    # Frontend
    "streamlit", "plotly", "altair",
    # HTTP
    "httpx", "httpcore", "anyio", "certifi",
    # Reporting
    "reportlab",
    # Licensing
    "cryptography",
    # Window
    "webview",
    # Misc
    "loguru", "pandas", "multipart",
]

ok, fail = [], []
for mod in REQUIRED:
    try:
        importlib.import_module(mod)
        ok.append(mod)
    except Exception as exc:
        fail.append((mod, str(exc)))

print(f"\n{'='*55}")
print(f"  Preflight: {len(ok)} ok, {len(fail)} missing")
print(f"{'='*55}")
if fail:
    print("\nMISSING:")
    for mod, err in fail:
        print(f"  ✗  {mod:<30} {err}")
else:
    print("\n  All imports OK — safe to build.")
print()
sys.exit(1 if fail else 0)
