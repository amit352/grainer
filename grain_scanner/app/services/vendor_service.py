"""Vendor management — CRUD + quality history aggregation."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Scan, Vendor


class VendorService:

    @staticmethod
    async def create_vendor(db: AsyncSession, data: dict) -> Vendor:
        vendor = Vendor(**data)
        db.add(vendor)
        await db.flush()
        return vendor

    @staticmethod
    async def list_vendors(db: AsyncSession) -> list[Vendor]:
        result = await db.execute(select(Vendor).order_by(Vendor.name))
        return list(result.scalars().all())

    @staticmethod
    async def get_vendor(db: AsyncSession, vendor_id: int) -> Vendor:
        result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
        vendor = result.scalar_one_or_none()
        if vendor is None:
            raise ValueError(f"Vendor {vendor_id} not found")
        return vendor

    @staticmethod
    async def update_vendor(db: AsyncSession, vendor_id: int, data: dict) -> Vendor:
        vendor = await VendorService.get_vendor(db, vendor_id)
        for k, v in data.items():
            if hasattr(vendor, k):
                setattr(vendor, k, v)
        await db.flush()
        return vendor

    @staticmethod
    async def delete_vendor(db: AsyncSession, vendor_id: int) -> None:
        vendor = await VendorService.get_vendor(db, vendor_id)
        await db.delete(vendor)
        await db.flush()

    @staticmethod
    async def get_vendor_scans(db: AsyncSession, vendor_id: int) -> list[Scan]:
        result = await db.execute(
            select(Scan)
            .where(Scan.vendor_id == vendor_id, Scan.status == "done")
            .order_by(Scan.processed_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def assign_vendor(db: AsyncSession, scan_id: int, vendor_id: int, lot_id: str = "") -> Scan:
        result = await db.execute(select(Scan).where(Scan.id == scan_id))
        scan = result.scalar_one_or_none()
        if scan is None:
            raise ValueError(f"Scan {scan_id} not found")
        scan.vendor_id = vendor_id
        if lot_id:
            scan.lot_id = lot_id
        await db.flush()
        return scan
