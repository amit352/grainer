"""Watershed segmentation for separating touching grains."""
from __future__ import annotations

import cv2
import numpy as np
from loguru import logger
from scipy.ndimage import gaussian_filter
from skimage.feature import peak_local_max
from skimage.segmentation import watershed


class WatershedSegmenter:
    """Separates touching grains using a distance-transform watershed.

    Hybrid marker strategy — adapts per blob:

    Single-grain blob (area ≤ 1.5 × median grain area):
        Threshold the smoothed distance map at 55 % of the blob's own peak.
        One connected core → one marker → one grain.  No peak-detection
        instability; an elongated grain is always one blob regardless of length.

    Multi-grain blob (area > 1.5 × median, i.e. likely touching grains):
        Estimate n = round(blob_area / median_grain_area).
        Run peak_local_max with min_distance ≈ 70 % of the typical grain
        radius and num_peaks = n.  Place a small disc marker at each peak.
        This finds the centre of each grain even when the binary mask has
        bridged the gap between them.
    """

    CORE_FRACTION   = 0.55   # distance fraction for single-grain cores
    MULTI_MIN_FRAC  = 0.70   # min_distance = MULTI_MIN_FRAC × typical_radius

    def __init__(self, min_distance: int = 20) -> None:
        self._min_distance = min_distance   # kept for API compatibility

    # ── Public ───────────────────────────────────────────────────────────────

    def segment(self, binary: np.ndarray) -> np.ndarray:
        """Return an integer-labelled array (0 = background, 1…N = grains)."""
        binary_u8 = binary.astype(np.uint8)
        labels = self._watershed_segment(binary_u8)
        if labels.max() == 0:
            logger.warning("Watershed found no markers — falling back to connected components")
            labels = self._cc_fallback(binary_u8)
        logger.debug(f"Segmentation found {labels.max()} regions")
        return labels

    # ── Private ──────────────────────────────────────────────────────────────

    def _watershed_segment(self, binary: np.ndarray) -> np.ndarray:
        # ── Distance transform ────────────────────────────────────────────────
        dist = cv2.distanceTransform(binary, cv2.DIST_L2, maskSize=5)

        # Light smoothing — removes single-pixel texture noise while keeping
        # the saddle valley between adjacent grains intact.
        dist_smooth = gaussian_filter(dist, sigma=1.5)

        # ── Connected blobs + size statistics ────────────────────────────────
        n_comp, comp_labels, comp_stats, _ = cv2.connectedComponentsWithStats(
            binary, connectivity=8
        )
        if n_comp <= 1:
            return np.zeros_like(binary, dtype=np.int32)

        all_areas = comp_stats[1:, cv2.CC_STAT_AREA].astype(float)

        # Estimate single-grain area from the lower 60th percentile of blob
        # areas (most blobs are single grains; the top 40 % are merged clusters
        # whose larger area would inflate the median).
        p60 = float(np.percentile(all_areas, 60))
        single_areas = all_areas[all_areas <= p60 * 1.5]
        if len(single_areas) == 0:
            single_areas = all_areas
        median_grain_area = float(np.median(single_areas))
        typical_radius    = float(np.sqrt(median_grain_area / np.pi))
        min_dist_px       = max(5, int(typical_radius * self.MULTI_MIN_FRAC))

        logger.debug(
            f"median_grain_area={median_grain_area:.0f}px "
            f"typical_radius={typical_radius:.1f}px "
            f"multi_min_dist={min_dist_px}px"
        )

        # ── Build sure-foreground markers ─────────────────────────────────────
        sure_fg = np.zeros_like(binary, dtype=np.uint8)

        for i in range(1, n_comp):
            blob_mask  = comp_labels == i
            blob_area  = float(comp_stats[i, cv2.CC_STAT_AREA])
            n_expected = max(1, round(blob_area / median_grain_area))

            # Isolate this blob's distance values
            local_dist = dist_smooth * blob_mask.astype(np.float32)
            local_max  = float(local_dist.max())
            if local_max < 1.0:
                continue

            if n_expected == 1:
                # ── Single grain: one connected core at 55 % depth ────────────
                sure_fg[blob_mask & (local_dist >= local_max * self.CORE_FRACTION)] = 1

            else:
                # ── Multi-grain blob: peak detection for n_expected grains ────
                # Stronger smoothing to suppress within-grain secondary peaks.
                sigma_peaks   = max(2.0, typical_radius * 0.25)
                local_smooth  = gaussian_filter(local_dist, sigma=sigma_peaks)
                dist_norm     = local_smooth / (local_smooth.max() + 1e-8)

                coords = peak_local_max(
                    dist_norm,
                    min_distance=min_dist_px,
                    labels=blob_mask,
                    exclude_border=False,
                    num_peaks=n_expected,
                )

                marker_r = max(2, int(typical_radius * 0.15))
                for r, c in coords:
                    cv2.circle(sure_fg, (int(c), int(r)), marker_r, 1, -1)

                logger.debug(
                    f"Blob {i}: area={blob_area:.0f} n_exp={n_expected} "
                    f"peaks_found={len(coords)}"
                )

        # ── Watershed from markers ────────────────────────────────────────────
        n_markers, markers = cv2.connectedComponents(sure_fg, connectivity=8)
        if n_markers <= 1:
            return self._cc_fallback(binary)

        labels: np.ndarray = watershed(
            -dist_smooth, markers, mask=binary.astype(bool)
        )
        return labels.astype(np.int32)

    @staticmethod
    def _cc_fallback(binary: np.ndarray) -> np.ndarray:
        n, labels, _, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        logger.debug(f"Connected-components fallback: {n - 1} components")
        return labels.astype(np.int32)
