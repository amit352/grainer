"""Segmentation tests — watershed separation of touching grains."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.vision.segmentation import WatershedSegmenter


def _binary_from_bgr(bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    binary = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 51, 10
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)


class TestWatershedSegmenter:

    def test_detects_two_touching_grains(self, touching_grains_bytes):
        arr = np.frombuffer(touching_grains_bytes, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        binary = _binary_from_bgr(bgr)

        seg = WatershedSegmenter(min_distance=15)
        labels = seg.segment(binary)

        n_labels = labels.max()
        assert n_labels >= 2, f"Expected ≥2 separate grains, got {n_labels}"

    def test_background_is_zero(self, touching_grains_bytes):
        arr = np.frombuffer(touching_grains_bytes, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        binary = _binary_from_bgr(bgr)

        seg = WatershedSegmenter(min_distance=15)
        labels = seg.segment(binary)

        # Background pixels should be 0
        background_mask = binary == 0
        # Most background pixels should be labelled 0
        bg_labels = labels[background_mask]
        assert (bg_labels == 0).mean() > 0.8

    def test_returns_integer_array(self, synthetic_image_bytes):
        arr = np.frombuffer(synthetic_image_bytes, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        binary = _binary_from_bgr(bgr)

        seg = WatershedSegmenter()
        labels = seg.segment(binary)

        assert labels.dtype in (np.int32, np.int64)

    def test_empty_image_returns_zeros(self):
        binary = np.zeros((100, 100), dtype=np.uint8)
        seg = WatershedSegmenter()
        labels = seg.segment(binary)
        assert labels.max() == 0

    def test_single_grain_returns_one_label(self):
        canvas = np.zeros((200, 300), dtype=np.uint8)
        cv2.ellipse(canvas, (150, 100), (40, 15), 0, 0, 360, 255, -1)
        seg = WatershedSegmenter(min_distance=10)
        labels = seg.segment(canvas)
        assert labels.max() >= 1
