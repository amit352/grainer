"""Cross-platform scanner driver.

Provides a unified interface to control flatbed scanners/printers via:
  - macOS/Linux: eSCL/AirScan (system printers via CUPS, no extra drivers)
  - macOS/Linux: ``scanimage`` (SANE via Homebrew)
  - macOS: ImageCapture CLI fallback
  - Windows: WIA via ``win32com`` (optional dependency)

Backend priority: eSCL → SANE → ImageCapture → WIA.

Usage::
    from app.scanner.driver import ScannerDriver, ScanOptions
    driver = ScannerDriver()
    devices = driver.list_devices()
    image_bytes = driver.scan(device_id=devices[0].id, options=ScanOptions(dpi=300))
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, Optional

from loguru import logger
from pydantic import BaseModel, Field


_PLATFORM = platform.system()  # "Darwin", "Linux", "Windows"


class ScannerDevice(BaseModel):
    """Metadata for a detected scanner/printer-scanner."""

    id: str
    name: str
    vendor: str = ""
    model: str = ""
    source: Literal["sane", "escl", "imagecapture", "wia", "mock"] = "sane"


class ScanOptions(BaseModel):
    """Parameters passed to the scanner hardware."""

    dpi: int = Field(300, ge=75, le=9600)
    color_mode: Literal["color", "gray", "lineart"] = "gray"
    format: Literal["png", "tiff", "jpeg"] = "png"
    source: Literal["Flatbed", "ADF", "ADF Front"] = "Flatbed"
    # Scan area (mm). None = full flatbed.
    left_mm: Optional[float] = None
    top_mm: Optional[float] = None
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None


class ScannerDriver:
    """Detects available scanners and triggers scans.

    Backend priority: eSCL (AirScan) → SANE → ImageCapture → WIA.
    eSCL works with any AirPrint printer already registered in macOS/Linux System
    Preferences — no extra drivers needed.
    """

    def __init__(self) -> None:
        self._backend = self._detect_backend()
        logger.info(f"Scanner backend selected: {self._backend}")

    # ── Public API ────────────────────────────────────────────────────────────

    def list_devices(self) -> list[ScannerDevice]:
        """Return all connected scanner devices."""
        try:
            if self._backend == "escl":
                return self._escl_list_devices()
            elif self._backend == "sane":
                return self._sane_list_devices()
            elif self._backend == "imagecapture":
                return self._imagecapture_list_devices()
            elif self._backend == "wia":
                return self._wia_list_devices()
            else:
                return []
        except Exception as exc:
            logger.error(f"list_devices failed: {exc}")
            return []

    def scan(
        self,
        device_id: str,
        options: ScanOptions | None = None,
    ) -> bytes:
        """Trigger a scan on *device_id* and return raw image bytes.

        Raises ``RuntimeError`` on hardware or backend failure.
        """
        if options is None:
            options = ScanOptions()

        logger.info(f"Scanning device={device_id!r} dpi={options.dpi} mode={options.color_mode}")

        if self._backend == "escl":
            return self._escl_scan(device_id, options)
        elif self._backend == "sane":
            return self._sane_scan(device_id, options)
        elif self._backend == "imagecapture":
            return self._imagecapture_scan(device_id, options)
        elif self._backend == "wia":
            return self._wia_scan(device_id, options)

        raise RuntimeError(f"No scanner backend available (detected: {self._backend})")

    def is_available(self) -> bool:
        return self._backend is not None

    # ── Backend detection ─────────────────────────────────────────────────────

    @staticmethod
    def _detect_backend() -> str | None:
        # eSCL: lpstat is built into macOS/Linux with CUPS (no install needed).
        # Preferred because it works with any AirPrint wireless printer.
        if shutil.which("lpstat"):
            return "escl"
        if shutil.which("scanimage"):
            return "sane"
        if _PLATFORM == "Darwin":
            if shutil.which("imagecapture") or Path("/usr/bin/imagecapture").exists():
                return "imagecapture"
        if _PLATFORM == "Windows":
            try:
                import win32com.client  # type: ignore[import]
                return "wia"
            except ImportError:
                pass
        logger.warning("No scanner backend found. Install SANE (brew install sane-backends) or use image upload.")
        return None

    # ── eSCL / AirScan backend ────────────────────────────────────────────────

    @staticmethod
    def _escl_list_devices() -> list[ScannerDevice]:
        from app.scanner.escl import ESCLBackend
        return ESCLBackend().list_devices()

    @staticmethod
    def _escl_scan(device_id: str, options: ScanOptions) -> bytes:
        from app.scanner.escl import ESCLBackend
        return ESCLBackend().scan(device_id, options)

    # ── SANE backend ──────────────────────────────────────────────────────────

    @staticmethod
    def _sane_list_devices() -> list[ScannerDevice]:
        result = subprocess.run(
            ["scanimage", "--list-devices"],
            capture_output=True, text=True, timeout=10
        )
        devices: list[ScannerDevice] = []
        for line in result.stdout.splitlines():
            # Format: device `epson2:libusb:001:005' is a EPSON GT-S650 flatbed scanner
            if line.startswith("device"):
                parts = line.split("`")
                if len(parts) >= 2:
                    dev_id = parts[1].split("'")[0]
                    rest = parts[1].split("'")[-1].strip()
                    vendor = rest.split()[2] if len(rest.split()) >= 3 else ""
                    model = " ".join(rest.split()[3:]).replace("flatbed scanner", "").strip()
                    devices.append(ScannerDevice(
                        id=dev_id, name=f"{vendor} {model}".strip(),
                        vendor=vendor, model=model, source="sane"
                    ))
        return devices

    @staticmethod
    def _sane_scan(device_id: str, options: ScanOptions) -> bytes:
        mode_map = {"gray": "Gray", "color": "Color", "lineart": "Lineart"}
        fmt_map = {"png": "png", "tiff": "tiff", "jpeg": "jpeg"}

        with tempfile.NamedTemporaryFile(suffix=f".{options.format}", delete=False) as tmp:
            out_path = Path(tmp.name)

        cmd = [
            "scanimage",
            f"--device-name={device_id}",
            f"--resolution={options.dpi}",
            f"--mode={mode_map[options.color_mode]}",
            f"--format={fmt_map[options.format]}",
            f"--source={options.source}",
            f"--output-file={out_path}",
        ]

        if options.left_mm is not None:
            cmd += [f"-l {options.left_mm}", f"-t {options.top_mm}",
                    f"-x {options.width_mm}", f"-y {options.height_mm}"]

        logger.debug(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            raise RuntimeError(f"scanimage failed: {result.stderr.strip()}")

        image_bytes = out_path.read_bytes()
        out_path.unlink(missing_ok=True)
        logger.info(f"Scan complete: {len(image_bytes)} bytes")
        return image_bytes

    # ── macOS ImageCapture backend ─────────────────────────────────────────────

    @staticmethod
    def _imagecapture_list_devices() -> list[ScannerDevice]:
        # ImageCapture CLI doesn't have a standard list command;
        # use system_profiler to find USB scanners.
        result = subprocess.run(
            ["system_profiler", "SPUSBDataType", "-json"],
            capture_output=True, text=True, timeout=10
        )
        devices: list[ScannerDevice] = []
        try:
            import json
            data = json.loads(result.stdout)
            usb_items = data.get("SPUSBDataType", [])
            for item in usb_items:
                for dev in item.get("_items", []):
                    name = dev.get("_name", "")
                    if any(k in name.lower() for k in ("scanner", "epson", "canon", "hp", "brother", "lexmark")):
                        devices.append(ScannerDevice(
                            id=dev.get("location_id", name),
                            name=name,
                            vendor=dev.get("manufacturer", ""),
                            source="imagecapture",
                        ))
        except Exception as exc:
            logger.debug(f"system_profiler parse error: {exc}")
        return devices

    @staticmethod
    def _imagecapture_scan(device_id: str, options: ScanOptions) -> bytes:
        # Use scanimage if available (preferred even on macOS), else error.
        if shutil.which("scanimage"):
            return ScannerDriver._sane_scan(device_id, options)
        raise RuntimeError(
            "ImageCapture CLI scan not directly supported. "
            "Install sane-backends via Homebrew: brew install sane-backends"
        )

    # ── Windows WIA backend ───────────────────────────────────────────────────

    @staticmethod
    def _wia_list_devices() -> list[ScannerDevice]:
        try:
            import win32com.client  # type: ignore[import]
            wia = win32com.client.Dispatch("WIA.DeviceManager")
            devices = []
            for info in wia.DeviceInfos:
                if info.Type == 1:  # WIA Scanner
                    devices.append(ScannerDevice(
                        id=info.DeviceID,
                        name=info.Properties["Name"].Value,
                        vendor=info.Properties.get("Manufacturer", {}).get("Value", ""),
                        source="wia",
                    ))
            return devices
        except Exception as exc:
            logger.error(f"WIA list failed: {exc}")
            return []

    @staticmethod
    def _wia_scan(device_id: str, options: ScanOptions) -> bytes:
        try:
            import win32com.client  # type: ignore[import]
            import tempfile

            wia = win32com.client.Dispatch("WIA.DeviceManager")
            device = None
            for info in wia.DeviceInfos:
                if info.DeviceID == device_id:
                    device = info.Connect()
                    break
            if device is None:
                raise RuntimeError(f"WIA device not found: {device_id}")

            # Set resolution
            scanner_item = device.Items[1]
            for prop in scanner_item.Properties:
                if prop.Name == "Horizontal Resolution":
                    prop.Value = options.dpi
                elif prop.Name == "Vertical Resolution":
                    prop.Value = options.dpi

            image = scanner_item.Transfer("{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}")  # PNG GUID

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                out_path = Path(tmp.name)

            image.SaveFile(str(out_path))
            data = out_path.read_bytes()
            out_path.unlink(missing_ok=True)
            return data
        except ImportError:
            raise RuntimeError("pywin32 not installed. Run: pip install pywin32")
        except Exception as exc:
            raise RuntimeError(f"WIA scan failed: {exc}") from exc
