"""Scanner hardware control endpoints."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import db_session
from app.core.config import settings
from app.scanner.driver import ScannerDevice, ScannerDriver, ScanOptions
from app.services.scan_service import ScanService

router = APIRouter(prefix="/scanner", tags=["scanner"])

# Module-level driver (lazy-initialised once per process).
_driver: ScannerDriver | None = None


def _get_driver() -> ScannerDriver:
    global _driver
    if _driver is None:
        _driver = ScannerDriver()
    return _driver


@router.get("/devices", summary="List connected scanner/printer devices")
async def list_devices() -> dict:
    """Detect all scanners available via eSCL/AirScan, SANE, ImageCapture, or WIA.

    Always returns 200. Check *backend_available* to know whether a driver
    was found — no scanner backend is a normal state, not a server error.
    """
    driver = _get_driver()
    if not driver.is_available():
        return {
            "backend_available": False,
            "backend": None,
            "devices": [],
            "install_hint": (
                "macOS/Linux: printers added in System Preferences are detected automatically via eSCL.  "
                "For USB scanners: brew install sane-backends  |  Windows: pip install pywin32"
            ),
        }
    devices = driver.list_devices()
    return {
        "backend_available": True,
        "backend": driver._backend,
        "devices": [d.model_dump() for d in devices],
        "install_hint": None,
    }


@router.post("/scan", summary="Trigger a scan from the connected device")
async def trigger_scan(
    device_id: str,
    dpi: int = settings.default_dpi,
    color_mode: Literal["color", "gray", "lineart"] = "gray",
    source: Literal["Flatbed", "ADF", "ADF Front"] = "Flatbed",
    db: AsyncSession = Depends(db_session),
) -> dict:
    """Scan directly from hardware and return a scan_id ready for processing.

    The captured image is saved and a Scan row is created (status=pending).
    """
    driver = _get_driver()
    if not driver.is_available():
        raise HTTPException(
            503,
            "No scanner backend available. Use /scans/upload to upload an image file instead.",
        )

    try:
        options = ScanOptions(dpi=dpi, color_mode=color_mode, source=source)
        image_bytes = driver.scan(device_id, options)
    except RuntimeError as exc:
        raise HTTPException(503, f"Scanner error: {exc}")

    # Build a meaningful filename from the device and timestamp
    import time
    filename = f"scan_{device_id.replace(':', '_').replace('/', '_')}_{int(time.time())}.png"

    scan = await ScanService.create_scan(
        db,
        image_bytes,
        filename,
        dpi,
        scanner_info={"device_id": device_id, "color_mode": color_mode, "source": source},
    )
    return {
        "scan_id": scan.id,
        "filename": scan.filename,
        "size_bytes": len(image_bytes),
        "status": scan.status,
        "message": f"Scan captured. POST /api/v1/scans/{scan.id}/process to analyse.",
    }


@router.post("/scan-and-process", summary="Scan and immediately process grains")
async def scan_and_process(
    device_id: str,
    dpi: int = settings.default_dpi,
    color_mode: Literal["color", "gray", "lineart"] = "gray",
    source: Literal["Flatbed", "ADF", "ADF Front"] = "Flatbed",
    db: AsyncSession = Depends(db_session),
):
    """One-shot: scan hardware → process → return full ScanResult."""
    trigger_result = await trigger_scan(device_id, dpi, color_mode, source, db)
    scan_id = trigger_result["scan_id"]

    from app.services.scan_service import ScanService
    # Use auto-detection so scanner images (light background / dark grains)
    # get the correct invert + adaptive-threshold params automatically.
    return await ScanService.process_scan(db, scan_id, params=None, auto_params=True)
