"""Pure domain models — no DB or HTTP concerns."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, computed_field


class ProcessingParams(BaseModel):
    """User-tunable vision pipeline parameters."""

    model_config = ConfigDict(frozen=True)

    dpi: int = Field(300, ge=72, le=9600, description="Scanner DPI")
    gaussian_blur_kernel: int = Field(5, ge=1, le=31, description="Gaussian blur kernel (odd)")
    adaptive_block_size: int = Field(51, ge=3, le=255, description="Adaptive threshold block size (odd)")
    adaptive_c: int = Field(10, ge=0, le=50, description="Adaptive threshold constant C")
    morph_kernel_size: int = Field(3, ge=1, le=21, description="Morphological op kernel size")
    morph_iterations: int = Field(2, ge=1, le=5, description="Morphological op iterations")
    watershed_min_distance: int = Field(20, ge=5, le=200, description="Minimum seed distance for watershed")
    min_grain_area_px: int = Field(50, ge=1, description="Minimum grain area (pixels)")
    max_grain_area_px: int = Field(5_000_000, ge=100, description="Maximum grain area (pixels)")
    invert_threshold: bool = Field(True, description="True when grains are darker than background")
    use_global_threshold: bool = Field(False, description="Use global Otsu instead of adaptive (better for high-contrast dark backgrounds)")
    reference_card: Optional[str] = Field(None, description="If set to 'credit', detect a credit/Aadhaar card (ISO 7810 ID-1) for auto-calibration")
    use_multichannel: bool = Field(True, description="Fuse grayscale, CLAHE, and saturation channels before segmentation for better recall")
    resegment_anomalies: bool = Field(True, description="Re-run watershed on touching/merged grains with tighter min_distance to force separation")


class BoundingBox(BaseModel):
    """Pixel-space bounding box (top-left origin)."""

    x: int
    y: int
    width: int
    height: int


class GrainMeasurement(BaseModel):
    """All measurements for a single detected grain."""

    grain_index: int = Field(..., description="Zero-based index within the scan")

    # ── Pixel measurements ───────────────────────────────────────────────────
    area_px: float
    perimeter_px: float
    major_axis_px: float
    minor_axis_px: float
    centroid_x_px: float
    centroid_y_px: float

    # ── Millimetre measurements ───────────────────────────────────────────────
    area_mm2: float
    perimeter_mm: float
    major_axis_mm: float
    minor_axis_mm: float
    centroid_x_mm: float
    centroid_y_mm: float

    # ── Derived ───────────────────────────────────────────────────────────────
    aspect_ratio: float = Field(..., ge=1.0)
    orientation_deg: float = Field(..., ge=-90.0, le=90.0)
    solidity: Optional[float] = None
    eccentricity: Optional[float] = None

    # ── Spatial ───────────────────────────────────────────────────────────────
    bbox: BoundingBox

    # ── Anomaly flags ─────────────────────────────────────────────────────────
    # Possible values: "touching" | "merged" | "oversized"
    anomaly_flags: list[str] = Field(default_factory=list)

    # Set True when this grain was recovered by re-splitting a touching cluster
    recovered_from_cluster: bool = False


class ClusterRegion(BaseModel):
    """An unresolved touching/merged cluster — excluded from quality scoring.

    Drawn as a red overlay on the annotated image with an estimated grain count.
    """
    bbox: BoundingBox
    estimated_count: int
    centroid_x_px: float
    centroid_y_px: float


class HistogramData(BaseModel):
    """Histogram bin data for a single metric."""

    bin_edges: list[float]
    counts: list[int]
    label: str
    unit: str


class ScanStatistics(BaseModel):
    """Aggregate statistics for all grains in a scan."""

    grain_count: int

    # Major axis (length)
    mean_major_axis_mm: float
    std_major_axis_mm: float
    min_major_axis_mm: float
    max_major_axis_mm: float

    # Minor axis (width)
    mean_minor_axis_mm: float
    std_minor_axis_mm: float
    min_minor_axis_mm: float
    max_minor_axis_mm: float

    # Area
    mean_area_mm2: float
    std_area_mm2: float
    min_area_mm2: float
    max_area_mm2: float

    # Aspect ratio
    mean_aspect_ratio: float
    std_aspect_ratio: float

    # Histograms
    major_axis_histogram: HistogramData
    minor_axis_histogram: HistogramData
    area_histogram: HistogramData


class ScanResult(BaseModel):
    """Complete result from processing one scan image."""

    scan_id: Optional[int] = None
    filename: str
    dpi: int
    image_width_px: int
    image_height_px: int
    image_width_mm: float
    image_height_mm: float
    # detected_count — grains measured individually (100% confidence, basis of quality report)
    detected_count: int = 0
    # cluster_estimated_count — grains estimated inside unresolvable touching clusters
    cluster_estimated_count: int = 0
    # grain_count — overall total (detected + estimated)
    grain_count: int = 0

    processing_time_s: float
    measurements: list[GrainMeasurement]
    statistics: ScanStatistics
    annotated_image_path: Optional[str] = None
    processed_at: datetime = Field(default_factory=datetime.utcnow)
    params: ProcessingParams

    # Spatial record of each unresolved cluster (for red overlay in annotated image)
    cluster_regions: list[ClusterRegion] = Field(default_factory=list)
