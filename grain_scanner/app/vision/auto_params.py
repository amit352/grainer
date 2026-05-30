"""Automatic pipeline parameter estimation from image content.

Analyses the raw image and returns a best-guess ProcessingParams so the user
never needs to manually tune invert_threshold, morph_kernel_size, or
watershed_min_distance for typical scanner images.
"""
from __future__ import annotations

import cv2
import numpy as np
from loguru import logger

from app.models.domain import ProcessingParams


def auto_detect_params(image_bytes: bytes, dpi: int = 300) -> ProcessingParams:
    """Return a ProcessingParams tuned to this specific image.

    Detects:
    - invert_threshold  — light-on-dark vs dark-on-light
    - morph_kernel_size — scaled to estimated grain size
    - watershed_min_distance — scaled to estimated grain radius
    - min_grain_area_px / max_grain_area_px — from grain size distribution
    """
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        logger.warning("auto_detect_params: could not decode image, using defaults")
        return ProcessingParams(dpi=dpi)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    invert, use_global = _detect_invert(gray)
    logger.info(f"Auto: invert_threshold={invert} use_global_threshold={use_global}")

    # Quick binary mask at guessed params to estimate grain size
    binary = _quick_binary(gray, invert, use_global)
    median_area_px, typical_radius_px = _estimate_grain_size(binary)
    logger.info(f"Auto: median_area={median_area_px:.0f}px  typical_radius={typical_radius_px:.1f}px")

    # Morph kernel: camera images (dark bg, global threshold) are high-contrast so
    # the binary mask is already clean. Use a SMALLER kernel + only 1 iteration to
    # avoid bridging the visible gaps between touching grains. Scanner images need
    # more closing to reconnect grain tips that are dimmer at the edges.
    if use_global:
        morph_k = _odd(max(3, min(5, int(typical_radius_px * 0.10))))
    else:
        morph_k = _odd(max(3, min(5, int(typical_radius_px * 0.10))))

    # Watershed min_distance:
    #   Scanner (adaptive): 50% of radius — grains are well-separated, low risk of over-split.
    #   Camera/dark-bg (global Otsu): 1.5× radius — elongated rice grains have distance-transform
    #   ridges up to 3× the circular radius; using a small min_distance splits one grain into
    #   multiple seeds (over-segmentation). 1.5× ensures only one seed per grain body.
    ws_ratio = 1.5 if use_global else 0.50
    ws_dist = max(10, int(typical_radius_px * ws_ratio))

    # Area bounds: accept grains from 25-35% to 250% of median.
    # Higher floor for global-threshold (camera) images — no scanner dust to worry about,
    # but grain-tip fragments can be ~20-30% of a full grain area.
    min_ratio = 0.35 if use_global else 0.25
    min_area = max(50, int(median_area_px * min_ratio))
    max_area = int(median_area_px * 2.5)

    # Camera images: 1 morph iteration — clean binary mask, avoid bridging grain gaps.
    # Scanner images: 2 morph iterations — close dimmer grain-tip gaps.
    morph_iters = 1 if use_global else 2

    params = ProcessingParams(
        dpi=dpi,
        invert_threshold=invert,
        use_global_threshold=use_global,
        morph_kernel_size=morph_k,
        morph_iterations=morph_iters,
        watershed_min_distance=ws_dist,
        min_grain_area_px=min_area,
        max_grain_area_px=max_area,
        resegment_anomalies=False,   # new segmentation handles separation natively
    )
    logger.info(
        f"Auto params → invert={invert} morph_k={morph_k} "
        f"ws_dist={ws_dist} min_area={min_area} max_area={max_area}"
    )
    return params


# ── Internal helpers ──────────────────────────────────────────────────────────

def _detect_invert(gray: np.ndarray) -> tuple[bool, bool]:
    """Return (invert, use_global_threshold).

    invert=True  → grains are dark on a light background (flatbed scanner).
    invert=False → grains are bright on a dark background (phone camera).

    use_global_threshold=True when Otsu gives a clean bimodal split — i.e. the
    image has high contrast (dark background + bright grains or vice-versa).
    Adaptive threshold is preferred for low-contrast scanner images because it
    handles uneven illumination; it breaks on uniform dark backgrounds where the
    local mean ≈ 0, making the threshold negative and flagging everything.
    """
    thresh_val, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright_fraction = float(np.mean(otsu == 255))
    invert = bright_fraction > 0.5

    # Estimate how bimodal the histogram is: if std of the gray image is high
    # AND the foreground fraction is small (<30%), Otsu gives a clean split.
    # Median brightness < 30 → background is dark (camera on black surface).
    # In that case adaptive threshold breaks (local mean ≈ 0 → threshold < 0 → all pixels pass).
    # Global Otsu gives a clean split when the image has a true bimodal distribution.
    img_median = float(np.median(gray))
    fg_fraction = min(bright_fraction, 1.0 - bright_fraction)  # minority class = foreground
    use_global = img_median < 30 and fg_fraction < 0.30

    logger.debug(
        f"_detect_invert: bright_fraction={bright_fraction:.3f} median={img_median:.1f} "
        f"fg={fg_fraction:.3f} → invert={invert} use_global={use_global}"
    )
    return invert, use_global


def _quick_binary(gray: np.ndarray, invert: bool, use_global: bool = False) -> np.ndarray:
    """Fast Otsu threshold to get a rough foreground mask for size estimation."""
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if invert:
        binary = cv2.bitwise_not(binary)
    # Light morphological close to connect fragments before size estimation
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    return binary


def _estimate_grain_size(binary: np.ndarray) -> tuple[float, float]:
    """Return (median_area_px, typical_radius_px) from connected components.

    Uses the 90th-percentile area as a "large grain" anchor so scanner
    artifacts (far smaller) don't drag the median down.
    """
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 1:
        return 500.0, 12.0  # safe fallback

    areas = stats[1:, cv2.CC_STAT_AREA].astype(float)  # skip background (label 0)

    # The 90th-percentile component is a representative "large grain".
    # Keep only components in [10%, 500%] of that anchor:
    #   - below 10%: scanner dust / tiny artifacts
    #   - above 500%: catastrophic multi-grain merges
    p90 = float(np.percentile(areas, 90))
    grain_areas = areas[(areas >= p90 * 0.10) & (areas <= p90 * 5.0)]
    if len(grain_areas) == 0:
        grain_areas = areas

    median_area = float(np.median(grain_areas))
    typical_radius = float(np.sqrt(median_area / np.pi))
    return median_area, typical_radius


def _odd(n: int) -> int:
    return n if n % 2 == 1 else n + 1
