"""PyInstaller runtime hook — runs before any user code."""
import os
import sys

if sys.platform == "win32":
    # Register all candidate DLL directories
    for d in [
        getattr(sys, "_MEIPASS", None),
        os.path.dirname(sys.executable),
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "System32"),
    ]:
        try:
            if d and os.path.isdir(d):
                os.add_dll_directory(d)
        except Exception:
            pass

    # Force-load _greenlet via ctypes so its DLL deps are resolved before
    # SQLAlchemy triggers the import through the normal mechanism.
    import ctypes
    import glob
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        for pyd in glob.glob(os.path.join(meipass, "_greenlet*.pyd")):
            try:
                ctypes.CDLL(pyd)
            except OSError as exc:
                # Print the exact missing DLL name to the console
                print(f"[hook] _greenlet load failed: {exc}", flush=True)
