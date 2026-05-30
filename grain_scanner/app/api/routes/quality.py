"""Quality grading endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import db_session
from app.models.quality import LotHistorySummary, QualityProfile, QualityReport
from app.services.export_service import ExportService
from app.services.quality_service import PROFILES, DEFAULT_PROFILE, QualityService
from app.services.scan_service import ScanService

router = APIRouter(prefix="/quality", tags=["quality"])


@router.get("/profiles", summary="List available quality profiles")
async def list_profiles() -> dict:
    return {
        "profiles": [p.model_dump() for p in PROFILES.values()],
        "default": DEFAULT_PROFILE,
    }


@router.get("/assess/{scan_id}", summary="Grade a scanned lot")
async def assess_scan(
    scan_id: int,
    profile_name: str = DEFAULT_PROFILE,
    lot_id: str = "",
    db: AsyncSession = Depends(db_session),
) -> QualityReport:
    """Run quality grading on an already-processed scan.

    Returns a QualityReport with grade (A/B/C/Reject), decision, and per-grain
    broken-grain classification.
    """
    try:
        scan = await ScanService._get_scan_or_raise(db, scan_id)
    except ValueError:
        raise HTTPException(404, f"Scan {scan_id} not found")
    if scan.status != "done":
        raise HTTPException(422, f"Scan {scan_id} is not processed yet (status={scan.status})")

    grains = await ScanService.get_grains(db, scan_id)
    if not grains:
        raise HTTPException(422, f"No measurements found for scan {scan_id}")

    from app.models.domain import BoundingBox, GrainMeasurement
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

    profile = PROFILES.get(profile_name)
    if profile is None:
        raise HTTPException(404, f"Profile {profile_name!r} not found. Available: {list(PROFILES)}")

    return QualityService.assess(measurements, profile=profile, scan_id=scan_id, lot_id=lot_id)


@router.get("/history", summary="Quality trend across all processed scans")
async def quality_history(
    profile_name: str = DEFAULT_PROFILE,
    limit: int = 50,
    db: AsyncSession = Depends(db_session),
) -> dict:
    """Return quality summaries for recent processed scans (newest first).

    Runs quality assessment on each scan on-the-fly using stored grain measurements.
    """
    from app.models.domain import BoundingBox, GrainMeasurement

    profile = PROFILES.get(profile_name)
    if profile is None:
        raise HTTPException(404, f"Profile {profile_name!r} not found. Available: {list(PROFILES)}")

    scans = await ScanService.list_scans(db, page=1, page_size=limit)
    done_scans = [s for s in scans if s.status == "done"]

    summaries: list[LotHistorySummary] = []
    for scan in done_scans:
        grains = await ScanService.get_grains(db, scan.id)
        if not grains:
            continue
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
        report = QualityService.assess(measurements, profile=profile, scan_id=scan.id)
        summaries.append(LotHistorySummary(
            scan_id=scan.id,
            filename=scan.filename,
            processed_at=scan.processed_at.isoformat() if scan.processed_at else None,
            profile_name=profile.name,
            grain_count=scan.grain_count or 0,
            grade=report.grade,
            total_score=report.total_score,
            head_rice_pct=report.head_rice_pct,
            total_broken_pct=report.total_broken_pct,
            foreign_matter_pct=report.foreign_matter_pct,
            decision=report.decision,
        ))

    return {
        "profile_name": profile_name,
        "scan_count": len(summaries),
        "summaries": [s.model_dump() for s in summaries],
    }


@router.get("/coa/{scan_id}", summary="Download Certificate of Analysis PDF")
async def download_coa(
    scan_id: int,
    profile_name: str = DEFAULT_PROFILE,
    lot_id: str = "",
    db: AsyncSession = Depends(db_session),
) -> Response:
    """Generate and return a single-page Certificate of Analysis PDF for a scan."""
    from app.models.domain import BoundingBox, GrainMeasurement

    try:
        scan = await ScanService._get_scan_or_raise(db, scan_id)
    except ValueError:
        raise HTTPException(404, f"Scan {scan_id} not found")
    if scan.status != "done":
        raise HTTPException(422, f"Scan {scan_id} is not processed yet (status={scan.status})")

    grains = await ScanService.get_grains(db, scan_id)
    if not grains:
        raise HTTPException(422, f"No measurements found for scan {scan_id}")

    profile = PROFILES.get(profile_name)
    if profile is None:
        raise HTTPException(404, f"Profile {profile_name!r} not found. Available: {list(PROFILES)}")

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

    report = QualityService.assess(measurements, profile=profile, scan_id=scan_id, lot_id=lot_id)

    try:
        pdf_bytes = ExportService.to_coa_pdf_bytes(
            quality_report=report.model_dump(),
            scan_filename=scan.filename,
            annotated_image_path=scan.annotated_path,
        )
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))

    lot_suffix = f"_{lot_id}" if lot_id else ""
    filename = f"coa_scan_{scan_id}{lot_suffix}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/assess-direct", summary="Grade measurements directly (no DB)")
async def assess_direct(
    profile_name: str = DEFAULT_PROFILE,
) -> dict:
    """Placeholder — use assess/{scan_id} for real scans."""
    return {"message": "POST measurements in request body — use assess/{scan_id} for DB-backed scans"}
