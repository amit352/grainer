"""
Grain Scanner License Server
----------------------------
POST /activate           — validate coupon + issue a signed license key
GET  /admin/coupons      — list all coupons              (requires X-Admin-Key)
POST /admin/coupons      — create one or more coupons    (requires X-Admin-Key)
DELETE /admin/coupons/{code} — revoke a coupon           (requires X-Admin-Key)

Environment variables (set in Railway dashboard):
  GRAIN_SCANNER_PRIVATE_KEY  — base64 Ed25519 private key
  ADMIN_KEY                  — secret for /admin/* endpoints
  DATABASE_URL               — optional; defaults to ./licenses.db
"""
from __future__ import annotations

import base64
import os
import secrets
import string
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

# ── Config ────────────────────────────────────────────────────────────────────

PRIVATE_KEY_B64 = os.environ["GRAIN_SCANNER_PRIVATE_KEY"]
ADMIN_KEY       = os.environ["ADMIN_KEY"]
DATABASE_URL    = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./licenses.db")

# ── Database ──────────────────────────────────────────────────────────────────

engine      = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Coupon(Base):
    __tablename__ = "coupons"
    id         = Column(Integer, primary_key=True)
    code       = Column(String(32), unique=True, nullable=False, index=True)
    max_uses   = Column(Integer, nullable=False, default=1)
    used_count = Column(Integer, nullable=False, default=0)
    note       = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class MachineLicense(Base):
    __tablename__ = "machine_licenses"
    id           = Column(Integer, primary_key=True)
    machine_id   = Column(String(64), unique=True, nullable=False, index=True)
    license_key  = Column(Text, nullable=False)
    coupon_code  = Column(String(32), nullable=False)
    activated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ── Licensing ─────────────────────────────────────────────────────────────────

def _sign(machine_id: str) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv_bytes = base64.b64decode(PRIVATE_KEY_B64)
    priv = Ed25519PrivateKey.from_private_bytes(priv_bytes)
    sig = priv.sign(machine_id.upper().encode())
    return base64.b64encode(sig).decode()


# ── Schemas ───────────────────────────────────────────────────────────────────

class ActivateRequest(BaseModel):
    machine_id:  str = Field(..., min_length=4, max_length=64)
    coupon_code: str = Field(..., min_length=1, max_length=32)


class ActivateResponse(BaseModel):
    license_key: str


class CouponIn(BaseModel):
    code:     str | None = None          # auto-generated if omitted
    max_uses: int        = Field(1, ge=1)
    note:     str | None = None
    count:    int        = Field(1, ge=1, le=100)   # bulk generation


class CouponOut(BaseModel):
    code:       str
    max_uses:   int
    used_count: int
    note:       str | None
    created_at: datetime


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Grain Scanner License Server", docs_url=None, redoc_url=None)


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _require_admin(x_admin_key: str = Header(...)):
    if not secrets.compare_digest(x_admin_key, ADMIN_KEY):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin key")


def _gen_code(length: int = 10) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ── Public endpoint ───────────────────────────────────────────────────────────

@app.post("/activate", response_model=ActivateResponse)
async def activate(req: ActivateRequest):
    machine_id  = req.machine_id.strip().upper()
    coupon_code = req.coupon_code.strip().upper()

    async with SessionLocal() as db:
        # Already activated on this machine → return the same key (idempotent)
        row = await db.scalar(
            select(MachineLicense).where(MachineLicense.machine_id == machine_id)
        )
        if row:
            return ActivateResponse(license_key=row.license_key)

        # Validate coupon
        coupon = await db.scalar(
            select(Coupon).where(Coupon.code == coupon_code)
        )
        if coupon is None:
            raise HTTPException(status_code=400, detail="Invalid coupon code.")
        if coupon.used_count >= coupon.max_uses:
            raise HTTPException(status_code=400, detail="Coupon has already been used.")

        # Issue license
        license_key = _sign(machine_id)

        coupon.used_count += 1
        db.add(MachineLicense(
            machine_id=machine_id,
            license_key=license_key,
            coupon_code=coupon_code,
        ))
        await db.commit()

    return ActivateResponse(license_key=license_key)


# ── Admin endpoints ───────────────────────────────────────────────────────────

@app.get("/admin/coupons", response_model=list[CouponOut])
async def list_coupons(x_admin_key: str = Header(...)):
    _require_admin(x_admin_key)
    async with SessionLocal() as db:
        rows = (await db.scalars(select(Coupon).order_by(Coupon.created_at.desc()))).all()
    return [CouponOut(code=r.code, max_uses=r.max_uses, used_count=r.used_count,
                      note=r.note, created_at=r.created_at) for r in rows]


@app.post("/admin/coupons", response_model=list[CouponOut], status_code=201)
async def create_coupons(body: CouponIn, x_admin_key: str = Header(...)):
    _require_admin(x_admin_key)
    created = []
    async with SessionLocal() as db:
        for i in range(body.count):
            code = (body.code if body.count == 1 and body.code else _gen_code()).upper()
            coupon = Coupon(code=code, max_uses=body.max_uses, note=body.note)
            db.add(coupon)
            created.append(coupon)
        await db.commit()
        for c in created:
            await db.refresh(c)
    return [CouponOut(code=c.code, max_uses=c.max_uses, used_count=c.used_count,
                      note=c.note, created_at=c.created_at) for c in created]


@app.delete("/admin/coupons/{code}", status_code=204)
async def revoke_coupon(code: str, x_admin_key: str = Header(...)):
    _require_admin(x_admin_key)
    async with SessionLocal() as db:
        coupon = await db.scalar(select(Coupon).where(Coupon.code == code.upper()))
        if coupon is None:
            raise HTTPException(status_code=404, detail="Coupon not found.")
        await db.delete(coupon)
        await db.commit()
