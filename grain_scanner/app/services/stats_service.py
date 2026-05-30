"""Aggregate statistics computation for a set of grain measurements."""
from __future__ import annotations

import numpy as np

from app.models.domain import GrainMeasurement, HistogramData, ScanStatistics


def compute_statistics(measurements: list[GrainMeasurement]) -> ScanStatistics:
    """Compute summary statistics and histograms from *measurements*."""
    if not measurements:
        return _empty_stats()

    major = np.array([m.major_axis_mm for m in measurements])
    minor = np.array([m.minor_axis_mm for m in measurements])
    area = np.array([m.area_mm2 for m in measurements])
    aspect = np.array([m.aspect_ratio for m in measurements])

    return ScanStatistics(
        grain_count=len(measurements),
        # major axis
        mean_major_axis_mm=float(major.mean()),
        std_major_axis_mm=float(major.std()),
        min_major_axis_mm=float(major.min()),
        max_major_axis_mm=float(major.max()),
        # minor axis
        mean_minor_axis_mm=float(minor.mean()),
        std_minor_axis_mm=float(minor.std()),
        min_minor_axis_mm=float(minor.min()),
        max_minor_axis_mm=float(minor.max()),
        # area
        mean_area_mm2=float(area.mean()),
        std_area_mm2=float(area.std()),
        min_area_mm2=float(area.min()),
        max_area_mm2=float(area.max()),
        # aspect ratio
        mean_aspect_ratio=float(aspect.mean()),
        std_aspect_ratio=float(aspect.std()),
        # histograms
        major_axis_histogram=_histogram(major, "Major Axis Length", "mm"),
        minor_axis_histogram=_histogram(minor, "Minor Axis Width", "mm"),
        area_histogram=_histogram(area, "Grain Area", "mm²"),
    )


def _histogram(values: np.ndarray, label: str, unit: str, bins: int = 20) -> HistogramData:
    counts, edges = np.histogram(values, bins=bins)
    return HistogramData(
        bin_edges=[round(float(e), 4) for e in edges],
        counts=[int(c) for c in counts],
        label=label,
        unit=unit,
    )


def _empty_stats() -> ScanStatistics:
    empty_hist = HistogramData(bin_edges=[0.0, 1.0], counts=[0], label="", unit="")
    return ScanStatistics(
        grain_count=0,
        mean_major_axis_mm=0.0,
        std_major_axis_mm=0.0,
        min_major_axis_mm=0.0,
        max_major_axis_mm=0.0,
        mean_minor_axis_mm=0.0,
        std_minor_axis_mm=0.0,
        min_minor_axis_mm=0.0,
        max_minor_axis_mm=0.0,
        mean_area_mm2=0.0,
        std_area_mm2=0.0,
        min_area_mm2=0.0,
        max_area_mm2=0.0,
        mean_aspect_ratio=0.0,
        std_aspect_ratio=0.0,
        major_axis_histogram=empty_hist,
        minor_axis_histogram=empty_hist,
        area_histogram=empty_hist,
    )
