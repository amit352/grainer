"""Measurement accuracy tests — ±0.05 mm tolerance on a known ellipse."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.vision.measurement import GrainMeasurer
from app.vision.segmentation import WatershedSegmenter


TOLERANCE_MM = 0.05  # ±0.05 mm accuracy target


class TestMeasurementAccuracy:

    def test_major_axis_within_tolerance(self, single_grain_bytes_and_truth):
        image_bytes, truth = single_grain_bytes_and_truth
        labels = _segment(image_bytes)
        dpi = truth["dpi"]
        measurer = GrainMeasurer(dpi=dpi, min_area_px=50)
        measurements = measurer.measure_all(labels)

        assert len(measurements) >= 1, "No grains detected in single-grain image"
        # Pick the largest grain (there should only be one)
        m = max(measurements, key=lambda x: x.major_axis_mm)
        err = abs(m.major_axis_mm - truth["major_mm"])
        assert err <= TOLERANCE_MM, (
            f"Major axis error {err:.4f} mm exceeds ±{TOLERANCE_MM} mm tolerance "
            f"(measured={m.major_axis_mm:.3f}, truth={truth['major_mm']})"
        )

    def test_minor_axis_within_tolerance(self, single_grain_bytes_and_truth):
        image_bytes, truth = single_grain_bytes_and_truth
        labels = _segment(image_bytes)
        dpi = truth["dpi"]
        measurer = GrainMeasurer(dpi=dpi, min_area_px=50)
        measurements = measurer.measure_all(labels)

        m = max(measurements, key=lambda x: x.major_axis_mm)
        err = abs(m.minor_axis_mm - truth["minor_mm"])
        assert err <= TOLERANCE_MM, (
            f"Minor axis error {err:.4f} mm exceeds ±{TOLERANCE_MM} mm tolerance"
        )

    def test_area_physically_reasonable(self, single_grain_bytes_and_truth):
        image_bytes, truth = single_grain_bytes_and_truth
        labels = _segment(image_bytes)
        measurer = GrainMeasurer(dpi=truth["dpi"], min_area_px=50)
        measurements = measurer.measure_all(labels)

        m = max(measurements, key=lambda x: x.major_axis_mm)
        # Ellipse area = π × (a/2) × (b/2)
        import math
        expected_area = math.pi * (truth["major_mm"] / 2) * (truth["minor_mm"] / 2)
        err = abs(m.area_mm2 - expected_area) / expected_area
        assert err < 0.15, f"Area error {err*100:.1f}% is too large"

    def test_aspect_ratio_correct(self, single_grain_bytes_and_truth):
        image_bytes, truth = single_grain_bytes_and_truth
        labels = _segment(image_bytes)
        measurer = GrainMeasurer(dpi=truth["dpi"], min_area_px=50)
        measurements = measurer.measure_all(labels)

        m = max(measurements, key=lambda x: x.major_axis_mm)
        expected_ar = truth["major_mm"] / truth["minor_mm"]
        err = abs(m.aspect_ratio - expected_ar)
        assert err < 0.3, f"Aspect ratio error {err:.3f} too large"

    def test_pixel_to_mm_conversion(self):
        dpi = 300
        px_per_mm = dpi / 25.4
        measurer = GrainMeasurer(dpi=dpi)
        assert abs(measurer._px_per_mm - px_per_mm) < 1e-6

    def test_bbox_within_image_bounds(self, single_grain_bytes_and_truth):
        image_bytes, truth = single_grain_bytes_and_truth
        labels = _segment(image_bytes)
        measurer = GrainMeasurer(dpi=truth["dpi"], min_area_px=50)
        measurements = measurer.measure_all(labels)

        for m in measurements:
            assert m.bbox.x >= 0
            assert m.bbox.y >= 0
            assert m.bbox.width > 0
            assert m.bbox.height > 0


def _segment(image_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    binary = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY_INV, 51, 10)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    seg = WatershedSegmenter(min_distance=15)
    return seg.segment(cleaned)
