"""Calibration module — pixel/mm conversion from DPI or reference marker."""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

import cv2
import numpy as np
from loguru import logger
from pydantic import BaseModel, Field


_MM_PER_INCH = 25.4


class CalibrationProfile(BaseModel):
    """Persisted pixel-per-mm calibration for a specific scanner setup."""

    name: str
    dpi: int
    px_per_mm: float
    reference_type: Literal["dpi", "ruler", "square", "circle"] = "dpi"
    reference_size_mm: Optional[float] = None
    reference_size_px: Optional[float] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def mm_per_px(self) -> float:
        return 1.0 / self.px_per_mm

    def px_to_mm(self, px: float) -> float:
        return px / self.px_per_mm

    def mm_to_px(self, mm: float) -> float:
        return mm * self.px_per_mm


class Calibrator:
    """Creates and persists CalibrationProfiles."""

    @staticmethod
    def from_dpi(dpi: int, name: str = "") -> CalibrationProfile:
        """Build a profile from scanner DPI — the simplest and most common case."""
        return CalibrationProfile(
            name=name or f"DPI-{dpi}",
            dpi=dpi,
            px_per_mm=dpi / _MM_PER_INCH,
            reference_type="dpi",
        )

    @staticmethod
    def from_reference_image(
        image_bytes: bytes,
        known_size_mm: float,
        reference_shape: Literal["square", "circle", "ruler"] = "square",
        name: str = "custom-calibration",
    ) -> CalibrationProfile:
        """Detect a reference marker in the image and compute px/mm from it.

        The reference marker should be a high-contrast square, circle, or ruler
        placed at the edge of the scan area.
        """
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("Cannot decode calibration image")

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

        if reference_shape in ("square", "ruler"):
            size_px = Calibrator._detect_square_marker(gray)
        else:
            size_px = Calibrator._detect_circle_marker(gray)

        if size_px is None:
            raise RuntimeError(
                "No reference marker detected. "
                "Ensure a high-contrast reference object is clearly visible."
            )

        px_per_mm = size_px / known_size_mm
        dpi = int(round(px_per_mm * _MM_PER_INCH))

        logger.info(
            f"Calibration: detected {size_px:.1f}px for {known_size_mm}mm → "
            f"{px_per_mm:.3f} px/mm ({dpi} DPI equivalent)"
        )

        return CalibrationProfile(
            name=name,
            dpi=dpi,
            px_per_mm=px_per_mm,
            reference_type=reference_shape,
            reference_size_mm=known_size_mm,
            reference_size_px=size_px,
        )

    @staticmethod
    def save(profile: CalibrationProfile, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(profile.model_dump_json(indent=2))
        logger.debug(f"Calibration profile saved to {path}")

    @staticmethod
    def load(path: Path) -> CalibrationProfile:
        if not path.exists():
            raise FileNotFoundError(f"Calibration file not found: {path}")
        return CalibrationProfile.model_validate_json(path.read_text())

    # ── Marker detection helpers ─────────────────────────────────────────────

    @staticmethod
    def _detect_square_marker(gray: np.ndarray) -> float | None:
        """Return the side length of the largest square-like contour in pixels."""
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        best: float | None = None
        best_score = -1.0
        total_px = gray.shape[0] * gray.shape[1]

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 100 or area > total_px * 0.5:
                continue

            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)

            # Prefer rectangles (4 corners) with aspect ratio near 1
            if len(approx) != 4:
                continue

            x, y, w, h = cv2.boundingRect(approx)
            ar = min(w, h) / max(w, h) if max(w, h) > 0 else 0
            score = ar * area
            if score > best_score:
                best_score = score
                best = (w + h) / 2.0  # average of width and height

        return best

    @staticmethod
    def _detect_circle_marker(gray: np.ndarray) -> float | None:
        """Return the diameter of the most prominent circle in pixels."""
        circles = cv2.HoughCircles(
            gray,
            cv2.HOUGH_GRADIENT,
            dp=1,
            minDist=50,
            param1=100,
            param2=30,
            minRadius=10,
            maxRadius=min(gray.shape) // 4,
        )
        if circles is None:
            return None

        circles = np.round(circles[0]).astype(int)
        # Return the radius × 2 of the largest circle
        largest = max(circles, key=lambda c: c[2])
        return float(largest[2] * 2)


# ── Reference-card auto-calibration ───────────────────────────────────────────

# Known card dimensions (ISO 7810 ID-1): credit cards, Aadhaar, driving licence
_CARD_W_MM = 85.60
_CARD_H_MM = 53.98
_CARD_ASPECT = _CARD_W_MM / _CARD_H_MM   # ≈ 1.586


def detect_card_px_per_mm(
    bgr: np.ndarray,
) -> tuple[float | None, np.ndarray | None]:
    """Detect a credit/Aadhaar card in *bgr* and return (px_per_mm, box_pts).

    *box_pts* is a (4,2) int32 array of the card's corner pixels, suitable for
    ``cv2.fillPoly`` to mask the card out of a binary image.

    Returns ``(None, None)`` when no card is found.
    """
    h, w = bgr.shape[:2]
    img_area = h * w

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 100)

    # Thick dilation closes gaps in card borders (printed text, wear)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    edges = cv2.dilate(edges, kernel, iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_score: float = float("inf")
    best: tuple | None = None

    for cnt in contours:
        area = cv2.contourArea(cnt)
        # Card must be 1 %–50 % of the image
        if area < 0.01 * img_area or area > 0.50 * img_area:
            continue

        rect = cv2.minAreaRect(cnt)
        bw, bh = rect[1]
        if bw < 1 or bh < 1:
            continue

        aspect = max(bw, bh) / min(bw, bh)
        aspect_err = abs(aspect - _CARD_ASPECT) / _CARD_ASPECT
        if aspect_err > 0.12:          # ±12 % tolerance
            continue

        # Must be reasonably rectangular
        rectangularity = area / (bw * bh)
        if rectangularity < 0.72:
            continue

        if aspect_err < best_score:
            best_score = aspect_err
            best = (rect, max(bw, bh), min(bw, bh))

    if best is None:
        logger.warning("Reference card not detected in image.")
        return None, None

    rect, long_px, short_px = best
    px_per_mm = (long_px / _CARD_W_MM + short_px / _CARD_H_MM) / 2
    box_pts = cv2.boxPoints(rect).astype(np.int32)
    logger.info(f"Card detected: {long_px:.0f}×{short_px:.0f} px → {px_per_mm:.3f} px/mm")
    return px_per_mm, box_pts
