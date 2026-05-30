"""Vendor management endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import db_session
from app.services.vendor_service import VendorService

router = APIRouter(prefix="/vendors", tags=["vendors"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class VendorCreate(BaseModel):
    name: str
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    commodity: str = "rice"
    price_per_kg: Optional[float] = None
    contract_notes: Optional[str] = None


class VendorUpdate(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    commodity: Optional[str] = None
    price_per_kg: Optional[float] = None
    contract_notes: Optional[str] = None


class VendorOut(BaseModel):
    id: int
    name: str
    contact_name: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    address: Optional[str]
    commodity: Optional[str]
    price_per_kg: Optional[float]
    contract_notes: Optional[str]
    created_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(cls, v) -> "VendorOut":
        return cls(
            id=v.id,
            name=v.name,
            contact_name=v.contact_name,
            phone=v.phone,
            email=v.email,
            address=v.address,
            commodity=v.commodity,
            price_per_kg=v.price_per_kg,
            contract_notes=v.contract_notes,
            created_at=v.created_at.isoformat(),
        )


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/", summary="List all vendors")
async def list_vendors(db: AsyncSession = Depends(db_session)) -> list[dict]:
    vendors = await VendorService.list_vendors(db)
    return [VendorOut.from_orm_obj(v).model_dump() for v in vendors]


@router.post("/", summary="Create a new vendor")
async def create_vendor(
    body: VendorCreate,
    db: AsyncSession = Depends(db_session),
) -> dict:
    try:
        vendor = await VendorService.create_vendor(db, body.model_dump(exclude_none=True))
    except Exception as exc:
        raise HTTPException(400, str(exc))
    return VendorOut.from_orm_obj(vendor).model_dump()


@router.get("/{vendor_id}", summary="Get vendor details")
async def get_vendor(vendor_id: int, db: AsyncSession = Depends(db_session)) -> dict:
    try:
        vendor = await VendorService.get_vendor(db, vendor_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return VendorOut.from_orm_obj(vendor).model_dump()


@router.put("/{vendor_id}", summary="Update vendor")
async def update_vendor(
    vendor_id: int,
    body: VendorUpdate,
    db: AsyncSession = Depends(db_session),
) -> dict:
    try:
        vendor = await VendorService.update_vendor(
            db, vendor_id, body.model_dump(exclude_none=True)
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return VendorOut.from_orm_obj(vendor).model_dump()


@router.delete("/{vendor_id}", summary="Delete vendor")
async def delete_vendor(vendor_id: int, db: AsyncSession = Depends(db_session)) -> dict:
    try:
        await VendorService.delete_vendor(db, vendor_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"deleted": vendor_id}


@router.post("/{vendor_id}/assign-scan/{scan_id}", summary="Link a scan to this vendor")
async def assign_scan(
    vendor_id: int,
    scan_id: int,
    lot_id: str = "",
    db: AsyncSession = Depends(db_session),
) -> dict:
    try:
        await VendorService.get_vendor(db, vendor_id)
        scan = await VendorService.assign_vendor(db, scan_id, vendor_id, lot_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"scan_id": scan.id, "vendor_id": vendor_id, "lot_id": scan.lot_id or ""}


@router.get("/{vendor_id}/history", summary="Quality history for a vendor")
async def vendor_history(
    vendor_id: int,
    profile_name: str = "Rice Standard",
    db: AsyncSession = Depends(db_session),
) -> dict:
    """Return quality assessment summaries for all done scans linked to this vendor."""
    from app.models.domain import BoundingBox, GrainMeasurement
    from app.models.quality import LotHistorySummary
    from app.services.quality_service import PROFILES, DEFAULT_PROFILE, QualityService
    from app.services.scan_service import ScanService

    try:
        vendor = await VendorService.get_vendor(db, vendor_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    profile = PROFILES.get(profile_name, PROFILES[DEFAULT_PROFILE])
    scans = await VendorService.get_vendor_scans(db, vendor_id)

    summaries = []
    for scan in scans:
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
            lot_id=scan.lot_id or "",
            profile_name=profile.name,
            grain_count=scan.grain_count or 0,
            grade=report.grade,
            total_score=report.total_score,
            head_rice_pct=report.head_rice_pct,
            total_broken_pct=report.total_broken_pct,
            foreign_matter_pct=report.foreign_matter_pct,
            decision=report.decision,
        ).model_dump())

    avg_score = sum(s["total_score"] for s in summaries) / len(summaries) if summaries else 0
    grade_dist = {}
    for s in summaries:
        grade_dist[s["grade"]] = grade_dist.get(s["grade"], 0) + 1

    return {
        "vendor": VendorOut.from_orm_obj(vendor).model_dump(),
        "profile_name": profile_name,
        "scan_count": len(summaries),
        "avg_quality_score": round(avg_score, 1),
        "grade_distribution": grade_dist,
        "summaries": summaries,
    }
