"""Calibration profile management endpoints."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import db_session
from app.calibration.calibrator import Calibrator, CalibrationProfile
from app.database.models import CalibrationProfileDB

router = APIRouter(prefix="/calibration", tags=["calibration"])


@router.get("/profiles", summary="List all calibration profiles")
async def list_profiles(db: AsyncSession = Depends(db_session)) -> list[dict]:
    result = await db.execute(select(CalibrationProfileDB).order_by(CalibrationProfileDB.created_at.desc()))
    profiles = result.scalars().all()
    return [_profile_to_dict(p) for p in profiles]


@router.post("/profiles/from-dpi", summary="Create a profile from DPI value")
async def create_from_dpi(
    dpi: int = Form(...),
    name: str = Form(""),
    db: AsyncSession = Depends(db_session),
) -> dict:
    profile = Calibrator.from_dpi(dpi, name)
    db_profile = _save_profile(db, profile)
    db.add(db_profile)
    await db.flush()
    return _profile_to_dict(db_profile)


@router.post("/profiles/from-image", summary="Auto-calibrate from a reference marker image")
async def create_from_image(
    file: UploadFile = File(...),
    known_size_mm: float = Form(...),
    reference_shape: Literal["square", "circle"] = Form("square"),
    name: str = Form("custom-calibration"),
    db: AsyncSession = Depends(db_session),
) -> dict:
    image_bytes = await file.read()
    try:
        profile = Calibrator.from_reference_image(image_bytes, known_size_mm, reference_shape, name)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc))

    db_profile = _save_profile(db, profile)
    db.add(db_profile)
    await db.flush()
    return _profile_to_dict(db_profile)


@router.put("/profiles/{profile_id}/activate", summary="Set profile as active")
async def activate_profile(profile_id: int, db: AsyncSession = Depends(db_session)) -> dict:
    # Deactivate all, then activate the chosen one.
    await db.execute(update(CalibrationProfileDB).values(is_active=False))
    result = await db.execute(
        select(CalibrationProfileDB).where(CalibrationProfileDB.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(404, f"Profile {profile_id} not found")
    profile.is_active = True
    await db.flush()
    return {"activated": profile_id}


@router.delete("/profiles/{profile_id}", summary="Delete a calibration profile")
async def delete_profile(profile_id: int, db: AsyncSession = Depends(db_session)) -> dict:
    result = await db.execute(
        select(CalibrationProfileDB).where(CalibrationProfileDB.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(404, f"Profile {profile_id} not found")
    await db.delete(profile)
    await db.flush()
    return {"deleted": profile_id}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save_profile(db: AsyncSession, profile: CalibrationProfile) -> CalibrationProfileDB:
    return CalibrationProfileDB(
        name=profile.name,
        dpi=profile.dpi,
        px_per_mm=profile.px_per_mm,
        reference_type=profile.reference_type,
        reference_size_mm=profile.reference_size_mm,
        reference_size_px=profile.reference_size_px,
        notes=profile.notes,
        is_active=False,
    )


def _profile_to_dict(p: CalibrationProfileDB) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "dpi": p.dpi,
        "px_per_mm": p.px_per_mm,
        "reference_type": p.reference_type,
        "reference_size_mm": p.reference_size_mm,
        "is_active": p.is_active,
        "created_at": p.created_at,
    }
