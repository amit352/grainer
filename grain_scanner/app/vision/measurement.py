"""Grain measurement engine — pixels → physical units."""
from __future__ import annotations

from typing import Sequence

import numpy as np
from loguru import logger
from skimage.measure import regionprops

from app.models.domain import BoundingBox, GrainMeasurement


_MM_PER_INCH = 25.4

# Anomaly thresholds
_SOLIDITY_TOUCHING  = 0.82   # below this → concave shape → likely two touching grains
_SOLIDITY_MERGED    = 0.90   # "merged" requires solidity below this (rules out normal elongated grains)
_AREA_SIGMA_FACTOR  = 1.5    # area > median + N*std → oversized (likely merged)
_EDT_MIN_DIST_FRAC  = 0.40   # EDT peak min_distance = frac × short side of bbox (was 0.25 — too sensitive)


class GrainMeasurer:
    """Converts a labelled image into a list of per-grain measurements."""

    def __init__(
        self,
        dpi: int,
        min_area_px: int = 50,
        max_area_px: int = 5_000_000,
    ) -> None:
        self._dpi = dpi
        self._px_per_mm = dpi / _MM_PER_INCH
        self._min_area = min_area_px
        self._max_area = max_area_px

    # ── Public ───────────────────────────────────────────────────────────────

    def measure_all(
        self,
        labels: np.ndarray,
        intensity_image: np.ndarray | None = None,
        filter_border: bool = True,
    ) -> list[GrainMeasurement]:
        """Return measurements for every valid grain in *labels*.

        Grains touching the image border are excluded by default — they are
        partial grains whose measurements would be unreliable.

        Each measurement carries *anomaly_flags*:
          - "touching"  — solidity < 0.82 (concave bridge between two grains)
          - "merged"    — ≥2 EDT peaks inside the region (watershed merge failure)
          - "oversized" — area > median + 1.5σ across the scan
        """
        props = regionprops(labels, intensity_image=intensity_image)
        h, w = labels.shape[:2]

        measurements: list[GrainMeasurement] = []
        skipped = 0
        grain_idx = 0

        for region in props:
            area = region.area
            if not (self._min_area <= area <= self._max_area):
                skipped += 1
                continue

            if filter_border:
                min_row, min_col, max_row, max_col = region.bbox
                if min_row <= 1 or min_col <= 1 or max_row >= h - 1 or max_col >= w - 1:
                    skipped += 1
                    continue

            flags = self._anomaly_flags_region(region, labels)
            m = self._measure_region(region, grain_idx, flags)
            grain_idx += 1
            measurements.append(m)

        # Population-level check: flag area outliers
        if measurements:
            areas = np.array([m.area_px for m in measurements])
            median_a = float(np.median(areas))
            std_a    = float(np.std(areas))
            threshold = median_a + _AREA_SIGMA_FACTOR * std_a
            for m in measurements:
                if m.area_px > threshold and not m.anomaly_flags:
                    m.anomaly_flags.append("oversized")

        n_anomalies = sum(1 for m in measurements if m.anomaly_flags)
        logger.debug(
            f"Measured {len(measurements)} grains "
            f"(skipped {skipped} outside area bounds, {n_anomalies} anomalies)"
        )
        return measurements

    def measure_single(self, labels: np.ndarray, label_id: int) -> GrainMeasurement | None:
        """Measure one specific label — useful for testing."""
        for idx, region in enumerate(regionprops(labels)):
            if region.label == label_id:
                return self._measure_region(region, idx, [])
        return None

    # ── Private ──────────────────────────────────────────────────────────────

    @staticmethod
    def _anomaly_flags_region(region, labels: np.ndarray) -> list[str]:
        """Return per-region anomaly flags before population stats are known."""
        flags: list[str] = []

        # 1. Solidity — concave indentation between touching grains
        solidity = float(region.solidity) if hasattr(region, "solidity") else 1.0
        if solidity < _SOLIDITY_TOUCHING:
            flags.append("touching")

        # 2. Distance-transform peak count — watershed merge failure
        min_row, min_col, max_row, max_col = region.bbox
        region_mask = (labels[min_row:max_row, min_col:max_col] == region.label)
        short_side = min(max_row - min_row, max_col - min_col)
        min_dist = max(5, int(short_side * _EDT_MIN_DIST_FRAC))

        try:
            from scipy.ndimage import distance_transform_edt
            from skimage.feature import peak_local_max
            dist = distance_transform_edt(region_mask)
            peaks = peak_local_max(dist, min_distance=min_dist, exclude_border=False)
            # Require both multiple EDT peaks AND reduced solidity — elongated but solid
            # grains naturally produce 2 peaks along their long axis at fine distances.
            if len(peaks) >= 2 and "touching" not in flags and solidity < _SOLIDITY_MERGED:
                flags.append("merged")
        except Exception:
            pass

        return flags

    def _measure_region(
        self, region, grain_index: int, anomaly_flags: list[str]
    ) -> GrainMeasurement:
        px = self._px_per_mm
        px2 = px * px

        major_px = float(region.major_axis_length)
        minor_px = float(region.minor_axis_length)
        if minor_px < 1e-6:
            minor_px = 1.0

        area_px  = float(region.area)
        perim_px = float(region.perimeter)
        cy_px, cx_px = region.centroid
        orient_deg = float(np.degrees(region.orientation))
        aspect = major_px / minor_px

        min_row, min_col, max_row, max_col = region.bbox
        bbox = BoundingBox(
            x=int(min_col), y=int(min_row),
            width=int(max_col - min_col), height=int(max_row - min_row),
        )

        return GrainMeasurement(
            grain_index=grain_index,
            area_px=area_px,
            perimeter_px=perim_px,
            major_axis_px=major_px,
            minor_axis_px=minor_px,
            centroid_x_px=float(cx_px),
            centroid_y_px=float(cy_px),
            area_mm2=area_px / px2,
            perimeter_mm=perim_px / px,
            major_axis_mm=major_px / px,
            minor_axis_mm=minor_px / px,
            centroid_x_mm=float(cx_px) / px,
            centroid_y_mm=float(cy_px) / px,
            aspect_ratio=float(max(aspect, 1.0)),
            orientation_deg=orient_deg,
            solidity=float(region.solidity) if hasattr(region, "solidity") else None,
            eccentricity=float(region.eccentricity) if hasattr(region, "eccentricity") else None,
            bbox=bbox,
            anomaly_flags=anomaly_flags,
        )
