"""Calibration module tests."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.calibration.calibrator import Calibrator, CalibrationProfile


class TestFromDPI:

    def test_px_per_mm_correct(self):
        profile = Calibrator.from_dpi(300)
        assert abs(profile.px_per_mm - 300 / 25.4) < 1e-6

    def test_name_uses_dpi(self):
        profile = Calibrator.from_dpi(600)
        assert "600" in profile.name

    def test_custom_name(self):
        profile = Calibrator.from_dpi(300, name="my-scanner")
        assert profile.name == "my-scanner"

    def test_px_to_mm_round_trip(self):
        profile = Calibrator.from_dpi(300)
        original_mm = 5.0
        px = profile.mm_to_px(original_mm)
        back_mm = profile.px_to_mm(px)
        assert abs(back_mm - original_mm) < 1e-9


class TestPersistence:

    def test_save_and_load_round_trip(self, tmp_path):
        profile = Calibrator.from_dpi(300, "test-profile")
        path = tmp_path / "calibration.json"
        Calibrator.save(profile, path)

        loaded = Calibrator.load(path)
        assert loaded.dpi == profile.dpi
        assert abs(loaded.px_per_mm - profile.px_per_mm) < 1e-9
        assert loaded.name == profile.name

    def test_load_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Calibrator.load(tmp_path / "nonexistent.json")


class TestReferenceImageCalibration:

    def _make_square_image(self, side_px: int = 200) -> bytes:
        """White canvas with a single black square."""
        canvas = np.full((600, 800, 3), 230, dtype=np.uint8)
        x, y = 300, 200
        cv2.rectangle(canvas, (x, y), (x + side_px, y + side_px), (10, 10, 10), -1)
        _, buf = cv2.imencode(".png", canvas)
        return buf.tobytes()

    def test_detects_square_marker(self):
        side_px = 200
        known_mm = 25.0  # 25 mm square
        image_bytes = self._make_square_image(side_px)

        profile = Calibrator.from_reference_image(image_bytes, known_mm, "square", "test")
        expected_px_per_mm = side_px / known_mm
        err = abs(profile.px_per_mm - expected_px_per_mm) / expected_px_per_mm
        assert err < 0.15, f"px/mm error {err*100:.1f}% too large"

    def test_invalid_image_raises(self):
        with pytest.raises(ValueError):
            Calibrator.from_reference_image(b"garbage", 25.0)

    def test_no_marker_raises(self):
        # Plain white image — no marker
        canvas = np.full((400, 600, 3), 230, dtype=np.uint8)
        _, buf = cv2.imencode(".png", canvas)
        with pytest.raises(RuntimeError, match="No reference marker"):
            Calibrator.from_reference_image(buf.tobytes(), 25.0)
