"""
Grain Scanner — Windows bundle entry point.

Start order:
  1. Verify machine license (shows Tkinter dialog if unlicensed)
  2. Set up per-user data directory (%APPDATA%/GrainScanner/)
  3. Start FastAPI on 127.0.0.1:8000 in a daemon thread
  4. Open the browser to localhost:8501
  5. Start Streamlit on port 8501 (main thread, blocking)
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import threading
import time


# ── Paths ─────────────────────────────────────────────────────────────────────

def _app_dir() -> pathlib.Path:
    """Bundle extraction dir when frozen; grain_scanner/ in dev mode."""
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys._MEIPASS)
    return pathlib.Path(__file__).resolve().parent.parent / "grain_scanner"


def _user_data_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        base = pathlib.Path(os.environ.get("APPDATA", "~")).expanduser() / "GrainScanner"
    else:
        base = pathlib.Path(__file__).resolve().parent.parent / "grain_scanner"
    base.mkdir(parents=True, exist_ok=True)
    for sub in ("data/uploads", "outputs", "logs"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


# ── License gate ──────────────────────────────────────────────────────────────

def _run_license_dialog(machine_id: str) -> None:
    """Show a Tkinter activation dialog; exit the process if user cancels."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print(f"\nGrain Scanner is not activated.\nMachine ID: {machine_id}\n"
              "Provide this ID and your coupon code at activation.",
              file=sys.stderr)
        sys.exit(1)

    from licensing import (  # noqa: PLC0415
        activate_with_coupon, save_license, verify_license,
        ActivationError,
    )

    root = tk.Tk()
    root.title("Grain Scanner — Activate")
    root.resizable(False, False)
    root.eval("tk::PlaceWindow . center")

    pad = {"padx": 20, "pady": 4}

    tk.Label(root, text="Activate Grain Scanner",
             font=("Segoe UI", 12, "bold")).pack(pady=(16, 2))
    tk.Label(root, text="Enter your coupon code to activate on this machine.",
             font=("Segoe UI", 9)).pack(**pad)

    # Machine ID row
    mid_frame = tk.Frame(root)
    mid_frame.pack(**pad)
    tk.Label(mid_frame, text="Machine ID:", font=("Segoe UI", 9), width=12, anchor="e").pack(side="left")
    mid_var = tk.StringVar(value=machine_id)
    tk.Entry(mid_frame, textvariable=mid_var, state="readonly", width=28,
             font=("Courier New", 10)).pack(side="left", padx=(4, 0))

    def _copy_id():
        root.clipboard_clear()
        root.clipboard_append(machine_id)

    tk.Button(mid_frame, text="Copy", command=_copy_id, width=5).pack(side="left", padx=4)

    # Coupon row
    coupon_frame = tk.Frame(root)
    coupon_frame.pack(**pad)
    tk.Label(coupon_frame, text="Coupon code:", font=("Segoe UI", 9), width=12, anchor="e").pack(side="left")
    coupon_var = tk.StringVar()
    coupon_entry = tk.Entry(coupon_frame, textvariable=coupon_var, width=28,
                            font=("Courier New", 10))
    coupon_entry.pack(side="left", padx=(4, 0))
    coupon_entry.focus_set()

    # Status label
    status_var = tk.StringVar()
    tk.Label(root, textvariable=status_var, font=("Segoe UI", 9),
             fg="red", wraplength=340, height=2).pack(pady=(4, 0))

    # Progress bar (shown while contacting server)
    progress = ttk.Progressbar(root, mode="indeterminate", length=200)
    progress.pack(pady=4)
    progress.pack_forget()

    activated = [False]

    def _do_activate():
        from tkinter import messagebox  # noqa: PLC0415

        coupon = coupon_var.get().strip()
        if not coupon:
            status_var.set("Please enter your coupon code.")
            return

        status_var.set("Contacting license server...")
        activate_btn.config(state="disabled")
        progress.pack(pady=4)
        progress.start(10)
        root.update()

        def _worker():
            try:
                key = activate_with_coupon(machine_id, coupon)
                if not verify_license(machine_id, key):
                    raise ActivationError("Server returned an invalid license key.")
                save_license(key)
                activated[0] = True
                root.after(0, root.destroy)
            except ActivationError as exc:
                err = str(exc)
                root.after(0, lambda: _on_error(err))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_error(msg: str):
        from tkinter import messagebox  # noqa: PLC0415
        progress.stop()
        progress.pack_forget()
        activate_btn.config(state="normal")
        status_var.set("")
        messagebox.showerror("Activation Failed", msg, parent=root)

    # Buttons
    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=12)
    activate_btn = tk.Button(btn_frame, text="Activate", command=_do_activate,
                             width=14, font=("Segoe UI", 9, "bold"))
    activate_btn.pack(side="left", padx=6)
    tk.Button(btn_frame, text="Exit", command=root.destroy, width=10,
              font=("Segoe UI", 9)).pack(side="left", padx=6)

    root.bind("<Return>", lambda _e: _do_activate())
    root.mainloop()

    if not activated[0]:
        sys.exit(0)


def _check_license() -> None:
    sys.path.insert(0, str(_app_dir()))
    from licensing import check_license, LicenseError  # noqa: PLC0415
    try:
        check_license()
    except LicenseError as exc:
        _run_license_dialog(exc.machine_id)


# ── Services ──────────────────────────────────────────────────────────────────

def _redirect_stdio(user_data: pathlib.Path) -> None:
    """When there is no attached console, write output to a log file."""
    if sys.stdout is None or not hasattr(sys.stdout, "fileno"):
        log_path = user_data / "logs" / "app.log"
        log_file = open(log_path, "a", buffering=1, encoding="utf-8")
        sys.stdout = log_file
        sys.stderr = log_file


def _start_api() -> None:
    import uvicorn
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        log_level="warning",
        access_log=False,
    )


def _start_ui(app_dir: pathlib.Path) -> None:
    from streamlit.web import cli as stcli  # noqa: PLC0415

    sys.argv = [
        "streamlit", "run",
        str(app_dir / "streamlit_app.py"),
        "--global.developmentMode=false",
        "--server.port=8501",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
        "--browser.serverAddress=localhost",
        "--server.enableCORS=false",
        "--server.enableXsrfProtection=false",
        "--logger.level=warning",
    ]
    stcli.main()


def _wait_for_streamlit(timeout: int = 30) -> bool:
    """Poll localhost:8501 until Streamlit responds or timeout."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen("http://localhost:8501", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app_dir   = _app_dir()
    user_data = _user_data_dir()

    _redirect_stdio(user_data)

    env_src = app_dir / ".env.example"
    env_dst = user_data / ".env"
    if env_src.exists() and not env_dst.exists():
        shutil.copy(env_src, env_dst)

    os.chdir(user_data)
    sys.path.insert(0, str(app_dir))

    _check_license()

    threading.Thread(target=_start_api, daemon=True, name="fastapi").start()
    threading.Thread(target=_start_ui, args=(app_dir,), daemon=True, name="streamlit").start()

    _wait_for_streamlit()

    import webview  # noqa: PLC0415
    webview.create_window(
        "Grain Scanner",
        "http://localhost:8501",
        width=1400,
        height=900,
        min_size=(900, 600),
    )
    webview.start(gui="edgechromium")

    _start_ui(app_dir)


if __name__ == "__main__":
    main()
