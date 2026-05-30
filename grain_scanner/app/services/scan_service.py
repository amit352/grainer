"""Business logic for scan lifecycle management."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database.models import Grain, Scan
from app.models.domain import GrainMeasurement, ProcessingParams, ScanResult
from app.vision.pipeline import ImageProcessor


_processor = ImageProcessor()


class ScanService:

    # ── Create ────────────────────────────────────────────────────────────────

    @staticmethod
    async def create_scan(
        db: AsyncSession,
        image_bytes: bytes,
        filename: str,
        dpi: int,
        scanner_info: Optional[dict] = None,
    ) -> Scan:
        """Persist an uploaded image and return a Scan row (status=pending)."""
        settings.ensure_dirs()
        dest = settings.upload_dir / filename
        dest.write_bytes(image_bytes)

        import cv2
        import numpy as np
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        h, w = bgr.shape[:2] if bgr is not None else (0, 0)
        px_per_mm = dpi / 25.4

        scan = Scan(
            filename=filename,
            original_path=str(dest),
            dpi=dpi,
            width_px=w,
            height_px=h,
            width_mm=w / px_per_mm,
            height_mm=h / px_per_mm,
            status="pending",
            scanner_info=scanner_info,
        )
        db.add(scan)
        await db.flush()
        logger.info(f"Created scan id={scan.id} file={filename}")
        return scan

    # ── Process ───────────────────────────────────────────────────────────────

    @staticmethod
    async def process_scan(
        db: AsyncSession,
        scan_id: int,
        params: Optional[ProcessingParams] = None,
        auto_params: bool = True,
    ) -> ScanResult:
        """Run the vision pipeline on an existing scan and persist results.

        When *auto_params* is True (default), the pipeline auto-detects invert,
        morph kernel, and watershed distance from the image content.
        Explicit *params* override auto-detection when provided.
        """
        scan = await ScanService._get_scan_or_raise(db, scan_id)

        scan.status = "processing"
        await db.flush()

        try:
            image_bytes = Path(scan.original_path).read_bytes()
            explicit_params = params is not None
            if params is None:
                params = ProcessingParams(dpi=scan.dpi)

            result = _processor.process(
                image_bytes, scan.filename, params,
                auto_params=(auto_params and not explicit_params),
            )

            # Persist grain rows
            for m in result.measurements:
                db.add(_grain_from_domain(scan.id, m))

            scan.grain_count = result.grain_count
            scan.processing_time_s = result.processing_time_s
            scan.annotated_path = result.annotated_image_path
            scan.processing_params = params.model_dump()
            scan.status = "done"
            scan.processed_at = datetime.utcnow()

            await db.flush()
            result.scan_id = scan.id
            logger.info(f"Scan id={scan_id} processed: {result.grain_count} grains")
            return result

        except Exception as exc:
            scan.status = "error"
            scan.error_message = str(exc)
            await db.flush()
            logger.error(f"Scan id={scan_id} failed: {exc}")
            raise

    # ── Read ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_scan(db: AsyncSession, scan_id: int) -> Scan:
        return await ScanService._get_scan_or_raise(db, scan_id)

    @staticmethod
    async def list_scans(
        db: AsyncSession, page: int = 1, page_size: int = 20
    ) -> list[Scan]:
        offset = (page - 1) * page_size
        result = await db.execute(
            select(Scan).order_by(Scan.created_at.desc()).offset(offset).limit(page_size)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_grains(db: AsyncSession, scan_id: int) -> list[Grain]:
        result = await db.execute(
            select(Grain).where(Grain.scan_id == scan_id).order_by(Grain.grain_index)
        )
        return list(result.scalars().all())

    # ── Delete ────────────────────────────────────────────────────────────────

    @staticmethod
    async def delete_scan(db: AsyncSession, scan_id: int) -> None:
        scan = await ScanService._get_scan_or_raise(db, scan_id)
        # Remove persisted files
        for path_str in (scan.original_path, scan.annotated_path):
            if path_str:
                p = Path(path_str)
                p.unlink(missing_ok=True)
        await db.delete(scan)
        await db.flush()
        logger.info(f"Deleted scan id={scan_id}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    async def _get_scan_or_raise(db: AsyncSession, scan_id: int) -> Scan:
        result = await db.execute(select(Scan).where(Scan.id == scan_id))
        scan = result.scalar_one_or_none()
        if scan is None:
            raise ValueError(f"Scan {scan_id} not found")
        return scan


def _grain_from_domain(scan_id: int, m: GrainMeasurement) -> Grain:
    return Grain(
        scan_id=scan_id,
        grain_index=m.grain_index,
        area_px=m.area_px,
        perimeter_px=m.perimeter_px,
        major_axis_px=m.major_axis_px,
        minor_axis_px=m.minor_axis_px,
        centroid_x_px=m.centroid_x_px,
        centroid_y_px=m.centroid_y_px,
        area_mm2=m.area_mm2,
        perimeter_mm=m.perimeter_mm,
        major_axis_mm=m.major_axis_mm,
        minor_axis_mm=m.minor_axis_mm,
        centroid_x_mm=m.centroid_x_mm,
        centroid_y_mm=m.centroid_y_mm,
        aspect_ratio=m.aspect_ratio,
        orientation_deg=m.orientation_deg,
        solidity=m.solidity,
        eccentricity=m.eccentricity,
        bbox_x=m.bbox.x,
        bbox_y=m.bbox.y,
        bbox_w=m.bbox.width,
        bbox_h=m.bbox.height,
    )
