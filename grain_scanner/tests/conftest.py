"""Shared test fixtures — synthetic grain images for deterministic testing."""
from __future__ import annotations

import io

import cv2
import numpy as np
import pytest

from app.models.domain import ProcessingParams


# ── Synthetic image factories ─────────────────────────────────────────────────

def make_synthetic_image(
    width: int = 1200,
    height: int = 800,
    n_grains: int = 10,
    dpi: int = 300,
    bg_color: int = 240,
    grain_color: int = 30,
    seed: int = 42,
) -> tuple[np.ndarray, list[dict]]:
    """Paint ellipses on a white canvas simulating rice grains.

    Returns (bgr_image, ground_truth_list).
    Each ground-truth dict has keys: cx, cy, major_px, minor_px, angle_deg.
    """
    rng = np.random.default_rng(seed)
    canvas = np.full((height, width, 3), bg_color, dtype=np.uint8)
    px_per_mm = dpi / 25.4
    gt = []

    for i in range(n_grains):
        # Random grain size (5–8 mm long, 2–3 mm wide — typical rice dimensions)
        major_mm = rng.uniform(5.0, 8.0)
        minor_mm = rng.uniform(2.0, 3.0)
        major_px = int(major_mm * px_per_mm)
        minor_px = int(minor_mm * px_per_mm)
        angle = float(rng.uniform(-80, 80))

        margin = max(major_px, minor_px) + 5
        cx = int(rng.uniform(margin, width - margin))
        cy = int(rng.uniform(margin, height - margin))

        cv2.ellipse(canvas, (cx, cy), (major_px // 2, minor_px // 2),
                    -angle, 0, 360, (grain_color, grain_color, grain_color), -1)
        gt.append({"cx": cx, "cy": cy, "major_px": major_px, "minor_px": minor_px, "angle_deg": angle})

    return canvas, gt


def image_to_bytes(bgr: np.ndarray, fmt: str = ".png") -> bytes:
    success, buf = cv2.imencode(fmt, bgr)
    assert success
    return buf.tobytes()


# ── Pytest fixtures ───────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def synthetic_image_bytes():
    """10-grain synthetic image as PNG bytes."""
    bgr, _ = make_synthetic_image(n_grains=10)
    return image_to_bytes(bgr)


@pytest.fixture(scope="session")
def synthetic_image_ground_truth():
    """Ground-truth grain info for the session-wide synthetic image."""
    _, gt = make_synthetic_image(n_grains=10)
    return gt


@pytest.fixture(scope="session")
def single_grain_bytes_and_truth():
    """Image with exactly one known ellipse — used for accuracy testing."""
    dpi = 300
    px_per_mm = dpi / 25.4
    major_mm = 6.0
    minor_mm = 2.5
    major_px = int(major_mm * px_per_mm)
    minor_px = int(minor_mm * px_per_mm)

    canvas = np.full((400, 600, 3), 240, dtype=np.uint8)
    cx, cy = 300, 200
    cv2.ellipse(canvas, (cx, cy), (major_px // 2, minor_px // 2), 30, 0, 360, (30, 30, 30), -1)

    return image_to_bytes(canvas), {
        "major_mm": major_mm,
        "minor_mm": minor_mm,
        "dpi": dpi,
    }


@pytest.fixture(scope="session")
def touching_grains_bytes():
    """Two overlapping ellipses that the watershed should separate."""
    canvas = np.full((400, 600, 3), 240, dtype=np.uint8)
    # Grain 1 at x=200
    cv2.ellipse(canvas, (200, 200), (35, 12), 0, 0, 360, (30, 30, 30), -1)
    # Grain 2 at x=260 — touching grain 1
    cv2.ellipse(canvas, (260, 200), (35, 12), 0, 0, 360, (30, 30, 30), -1)
    return image_to_bytes(canvas)


@pytest.fixture
def default_params():
    return ProcessingParams(dpi=300)
