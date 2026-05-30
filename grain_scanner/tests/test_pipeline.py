"""End-to-end pipeline tests on synthetic images."""
from __future__ import annotations

import pytest

from app.models.domain import ProcessingParams
from app.vision.pipeline import ImageProcessor


@pytest.fixture(scope="module")
def processor():
    return ImageProcessor()


class TestEndToEnd:

    def test_processes_without_error(self, processor, synthetic_image_bytes, default_params):
        result = processor.process(synthetic_image_bytes, "test.png", default_params, save_annotated=False)
        assert result is not None

    def test_detects_at_least_8_grains(self, processor, synthetic_image_bytes, default_params):
        result = processor.process(synthetic_image_bytes, "test.png", default_params, save_annotated=False)
        assert result.grain_count >= 8, f"Expected ≥8 grains, got {result.grain_count}"

    def test_processing_time_reasonable(self, processor, synthetic_image_bytes, default_params):
        result = processor.process(synthetic_image_bytes, "test.png", default_params, save_annotated=False)
        assert result.processing_time_s < 30.0, f"Too slow: {result.processing_time_s:.2f}s"

    def test_result_dimensions_match(self, processor, synthetic_image_bytes, default_params):
        result = processor.process(synthetic_image_bytes, "test.png", default_params, save_annotated=False)
        # image is 1200×800 px at 300 DPI → ~101.6×67.7 mm
        assert result.image_width_px == 1200
        assert result.image_height_px == 800
        assert abs(result.image_width_mm - 101.6) < 1.0

    def test_measurements_have_correct_count(self, processor, synthetic_image_bytes, default_params):
        result = processor.process(synthetic_image_bytes, "test.png", default_params, save_annotated=False)
        assert len(result.measurements) == result.grain_count

    def test_all_mm_values_positive(self, processor, synthetic_image_bytes, default_params):
        result = processor.process(synthetic_image_bytes, "test.png", default_params, save_annotated=False)
        for m in result.measurements:
            assert m.major_axis_mm > 0
            assert m.minor_axis_mm > 0
            assert m.area_mm2 > 0
            assert m.perimeter_mm > 0

    def test_aspect_ratio_ge_1(self, processor, synthetic_image_bytes, default_params):
        result = processor.process(synthetic_image_bytes, "test.png", default_params, save_annotated=False)
        for m in result.measurements:
            assert m.aspect_ratio >= 1.0, f"Grain {m.grain_index} has aspect_ratio < 1"

    def test_statistics_consistent(self, processor, synthetic_image_bytes, default_params):
        result = processor.process(synthetic_image_bytes, "test.png", default_params, save_annotated=False)
        stats = result.statistics
        assert stats.grain_count == result.grain_count
        assert stats.min_major_axis_mm <= stats.mean_major_axis_mm <= stats.max_major_axis_mm

    def test_invalid_bytes_raises(self, processor, default_params):
        with pytest.raises(ValueError, match="Could not decode"):
            processor.process(b"not_an_image", "bad.png", default_params, save_annotated=False)
