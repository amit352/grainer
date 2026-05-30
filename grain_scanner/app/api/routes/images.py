"""Scan upload, processing, and retrieval endpoints."""
from __future__ import annotations

import asyncio
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import db_session
from app.core.config import settings
from app.models.domain import ProcessingParams, ScanResult
from app.services.scan_service import ScanService

router = APIRouter(prefix="/scans", tags=["scans"])


@router.post("/upload", summary="Upload a scan image")
async def upload_scan(
    file: UploadFile = File(...),
    dpi: int = Form(settings.default_dpi),
    vendor_id: Optional[int] = Form(None),
    lot_id: str = Form(""),
    db: AsyncSession = Depends(db_session),
) -> dict:
    """Accepts PNG, JPEG, or TIFF. Returns scan_id for subsequent processing."""
    if file.content_type not in ("image/png", "image/jpeg", "image/tiff", "image/x-tiff"):
        raise HTTPException(400, "Unsupported file type. Upload PNG, JPEG, or TIFF.")

    image_bytes = await file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(image_bytes) > max_bytes:
        raise HTTPException(413, f"File too large (max {settings.max_upload_size_mb} MB)")

    scan = await ScanService.create_scan(db, image_bytes, file.filename or "scan.png", dpi)

    if vendor_id is not None or lot_id:
        from app.services.vendor_service import VendorService
        try:
            if vendor_id is not None:
                await VendorService.assign_vendor(db, scan.id, vendor_id, lot_id)
            elif lot_id:
                # Store lot_id without vendor
                from sqlalchemy import select
                from app.database.models import Scan as ScanModel
                result = await db.execute(select(ScanModel).where(ScanModel.id == scan.id))
                s = result.scalar_one_or_none()
                if s:
                    s.lot_id = lot_id
                    await db.flush()
        except Exception:
            pass  # vendor assignment is best-effort; don't fail the upload

    return {"scan_id": scan.id, "filename": scan.filename, "status": scan.status}


@router.post("/{scan_id}/process", summary="Process a previously uploaded scan")
async def process_scan(
    scan_id: int,
    params: Optional[ProcessingParams] = None,
    db: AsyncSession = Depends(db_session),
) -> ScanResult:
    try:
        return await ScanService.process_scan(db, scan_id, params)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        logger.error(f"Processing scan {scan_id} failed: {exc}")
        raise HTTPException(500, f"Processing failed: {exc}")


@router.get("/{scan_id}", summary="Get scan metadata")
async def get_scan(scan_id: int, db: AsyncSession = Depends(db_session)) -> dict:
    try:
        scan = await ScanService.get_scan(db, scan_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {
        "id": scan.id,
        "filename": scan.filename,
        "dpi": scan.dpi,
        "width_mm": scan.width_mm,
        "height_mm": scan.height_mm,
        "grain_count": scan.grain_count,
        "status": scan.status,
        "processing_time_s": scan.processing_time_s,
        "created_at": scan.created_at,
        "processed_at": scan.processed_at,
        "error_message": scan.error_message,
    }


@router.get("/", summary="List scan history")
async def list_scans(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(db_session),
) -> list[dict]:
    scans = await ScanService.list_scans(db, page, page_size)
    return [
        {
            "id": s.id,
            "filename": s.filename,
            "dpi": s.dpi,
            "grain_count": s.grain_count,
            "status": s.status,
            "created_at": s.created_at,
        }
        for s in scans
    ]


@router.delete("/{scan_id}", summary="Delete a scan and its grains")
async def delete_scan(scan_id: int, db: AsyncSession = Depends(db_session)) -> dict:
    try:
        await ScanService.delete_scan(db, scan_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"deleted": scan_id}


@router.post("/batch", summary="Upload and process multiple scan images in one request")
async def batch_process(
    files: list[UploadFile] = File(...),
    dpi: int = Form(settings.default_dpi),
    profile_name: str = Form("Rice Standard"),
    lot_id_prefix: str = Form(""),
    vendor_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(db_session),
) -> list[dict]:
    """Process multiple images sequentially. Returns per-file grade results."""
    from app.database.models import Scan as ScanModel
    from app.models.domain import BoundingBox, GrainMeasurement
    from app.services.quality_service import PROFILES, QualityService
    from app.services.vendor_service import VendorService
    from sqlalchemy import select

    profile = PROFILES.get(profile_name)
    results: list[dict] = []

    for i, file in enumerate(files):
        fname = file.filename or f"batch_{i + 1}.png"
        lot_id = f"{lot_id_prefix}-{i + 1}" if lot_id_prefix else ""

        if file.content_type not in ("image/png", "image/jpeg", "image/tiff", "image/x-tiff"):
            results.append({"filename": fname, "lot_id": lot_id, "status": "error",
                            "error": "Unsupported file type"})
            continue

        image_bytes = await file.read()
        if len(image_bytes) > settings.max_upload_size_mb * 1024 * 1024:
            results.append({"filename": fname, "lot_id": lot_id, "status": "error",
                            "error": f"File too large (max {settings.max_upload_size_mb} MB)"})
            continue

        try:
            scan = await ScanService.create_scan(db, image_bytes, fname, dpi)

            if vendor_id is not None:
                try:
                    await VendorService.assign_vendor(db, scan.id, vendor_id, lot_id)
                except Exception:
                    pass
            elif lot_id:
                r = await db.execute(select(ScanModel).where(ScanModel.id == scan.id))
                s = r.scalar_one_or_none()
                if s:
                    s.lot_id = lot_id
                    await db.flush()

            result = await ScanService.process_scan(db, scan.id, None)

            entry: dict = {
                "filename": fname,
                "lot_id": lot_id,
                "scan_id": scan.id,
                "status": "done",
                "grain_count": result.grain_count,
                "processing_time_s": round(result.processing_time_s, 2),
            }

            if profile:
                grains = await ScanService.get_grains(db, scan.id)
                measurements = [
                    GrainMeasurement(
                        grain_index=g.grain_index,
                        area_px=g.area_px, perimeter_px=g.perimeter_px,
                        major_axis_px=g.major_axis_px, minor_axis_px=g.minor_axis_px,
                        centroid_x_px=g.centroid_x_px, centroid_y_px=g.centroid_y_px,
                        area_mm2=g.area_mm2, perimeter_mm=g.perimeter_mm,
                        major_axis_mm=g.major_axis_mm, minor_axis_mm=g.minor_axis_mm,
                        centroid_x_mm=g.centroid_x_mm, centroid_y_mm=g.centroid_y_mm,
                        aspect_ratio=g.aspect_ratio, orientation_deg=g.orientation_deg,
                        solidity=g.solidity, eccentricity=g.eccentricity,
                        bbox=BoundingBox(x=g.bbox_x, y=g.bbox_y, width=g.bbox_w, height=g.bbox_h),
                    )
                    for g in grains
                ]
                qr = QualityService.assess(measurements, profile=profile,
                                           scan_id=scan.id, lot_id=lot_id)
                entry.update({
                    "grade": qr.grade,
                    "total_score": qr.total_score,
                    "decision": qr.decision,
                    "head_rice_pct": round(qr.head_rice_pct, 1),
                    "total_broken_pct": round(qr.total_broken_pct, 1),
                    "foreign_matter_pct": round(qr.foreign_matter_pct, 1),
                })

            results.append(entry)
            logger.info(f"Batch [{i+1}/{len(files)}] {fname} → grade={entry.get('grade','?')}")

        except Exception as exc:
            logger.error(f"Batch item {fname} failed: {exc}")
            results.append({"filename": fname, "lot_id": lot_id, "status": "error", "error": str(exc)})

    return results


@router.get("/{scan_id}/annotated-image", summary="Return annotated PNG")
async def get_annotated_image(scan_id: int, db: AsyncSession = Depends(db_session)):
    try:
        scan = await ScanService.get_scan(db, scan_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    if not scan.annotated_path:
        raise HTTPException(404, "Annotated image not yet generated")
    return FileResponse(scan.annotated_path, media_type="image/png")
