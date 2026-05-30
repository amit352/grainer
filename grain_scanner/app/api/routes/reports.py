"""CSV and PDF export endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import db_session
from app.services.export_service import ExportService
from app.services.scan_service import ScanService
from app.services.stats_service import compute_statistics
from app.api.routes.measurements import _grain_to_domain

router = APIRouter(prefix="/scans", tags=["reports"])


@router.get("/{scan_id}/export/csv", summary="Download measurements as CSV")
async def export_csv(scan_id: int, db: AsyncSession = Depends(db_session)):
    try:
        scan = await ScanService.get_scan(db, scan_id)
        grains = await ScanService.get_grains(db, scan_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    csv_bytes = ExportService.to_csv_bytes(grains)
    filename = f"scan_{scan_id}_{scan.filename.rsplit('.', 1)[0]}_grains.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{scan_id}/export/pdf", summary="Download full PDF report")
async def export_pdf(scan_id: int, db: AsyncSession = Depends(db_session)):
    try:
        scan = await ScanService.get_scan(db, scan_id)
        grains = await ScanService.get_grains(db, scan_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    measurements = [_grain_to_domain(g) for g in grains]
    stats = compute_statistics(measurements)

    try:
        pdf_bytes = ExportService.to_pdf_bytes(scan, grains, stats, scan.annotated_path)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))

    filename = f"scan_{scan_id}_report.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
