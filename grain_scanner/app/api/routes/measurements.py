"""Measurement and statistics endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import db_session
from app.models.domain import GrainMeasurement, ScanStatistics
from app.services.scan_service import ScanService
from app.services.stats_service import compute_statistics
from app.database.models import Grain
from app.models.domain import BoundingBox

router = APIRouter(prefix="/scans", tags=["measurements"])


@router.get("/{scan_id}/measurements", summary="Per-grain measurements")
async def get_measurements(
    scan_id: int, db: AsyncSession = Depends(db_session)
) -> list[GrainMeasurement]:
    try:
        grains = await ScanService.get_grains(db, scan_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    return [_grain_to_domain(g) for g in grains]


@router.get("/{scan_id}/statistics", summary="Aggregate statistics for a scan")
async def get_statistics(
    scan_id: int, db: AsyncSession = Depends(db_session)
) -> ScanStatistics:
    try:
        grains = await ScanService.get_grains(db, scan_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    measurements = [_grain_to_domain(g) for g in grains]
    return compute_statistics(measurements)


def _grain_to_domain(g: Grain) -> GrainMeasurement:
    return GrainMeasurement(
        grain_index=g.grain_index,
        area_px=g.area_px,
        perimeter_px=g.perimeter_px,
        major_axis_px=g.major_axis_px,
        minor_axis_px=g.minor_axis_px,
        centroid_x_px=g.centroid_x_px,
        centroid_y_px=g.centroid_y_px,
        area_mm2=g.area_mm2,
        perimeter_mm=g.perimeter_mm,
        major_axis_mm=g.major_axis_mm,
        minor_axis_mm=g.minor_axis_mm,
        centroid_x_mm=g.centroid_x_mm,
        centroid_y_mm=g.centroid_y_mm,
        aspect_ratio=g.aspect_ratio,
        orientation_deg=g.orientation_deg,
        solidity=g.solidity,
        eccentricity=g.eccentricity,
        bbox=BoundingBox(x=g.bbox_x, y=g.bbox_y, width=g.bbox_w, height=g.bbox_h),
    )
