"""Annotated image generation for grain scan results."""
from __future__ import annotations

import math
from typing import Sequence

import cv2
import numpy as np

from app.models.domain import GrainMeasurement


# Colour palette (BGR)
_CONTOUR_COLOR      = (0, 220, 80)    # vivid green  — normal grain
_CONTOUR_RECOVERED  = (255, 200, 0)   # cyan-blue    — recovered from cluster split
_CLUSTER_FILL       = (0, 0, 180)     # dark red fill (semi-transparent)
_CLUSTER_BORDER     = (0, 0, 220)     # red border
_AXIS_MAJOR_COLOR   = (0, 180, 255)   # orange-amber
_AXIS_MINOR_COLOR   = (255, 80, 80)   # blue-ish
_CENTROID_COLOR     = (0, 220, 255)   # yellow
_TEXT_COLOR         = (255, 255, 255) # white
_TEXT_BG_COLOR      = (30, 30, 30)    # near-black
_TEXT_BG_RECOVERED  = (120, 60, 0)    # dark cyan bg for recovered labels


def _ellipse_color(m) -> tuple[int, int, int]:
    if getattr(m, "recovered_from_cluster", False):
        return _CONTOUR_RECOVERED
    return _CONTOUR_COLOR


class GrainVisualizer:
    """Draws contours, axes, IDs, and measurements on a copy of the source image."""

    def __init__(
        self,
        show_axes: bool = True,
        show_ids: bool = True,
        show_mm_labels: bool = False,   # off by default — too cluttered on real scans
        font_scale: float = 0.0,        # 0 = auto-scale to image size
        line_thickness: int = 1,
    ) -> None:
        self._show_axes = show_axes
        self._show_ids = show_ids
        self._show_mm = show_mm_labels
        self._font_scale = font_scale
        self._thickness = line_thickness

    # ── Public ───────────────────────────────────────────────────────────────

    def annotate(
        self,
        bgr_image: np.ndarray,
        measurements: list[GrainMeasurement],
        labels: np.ndarray | None = None,
        cluster_regions: list | None = None,
    ) -> np.ndarray:
        """Return an annotated copy of *bgr_image*.

        Normal grains are drawn in green; recovered grains in cyan.
        Unresolved cluster regions are drawn as semi-transparent red boxes
        with an estimated grain count (~N).
        """
        canvas = bgr_image.copy()
        h, w = canvas.shape[:2]

        font_scale = self._font_scale if self._font_scale > 0 else max(0.3, w / 2000.0)

        if labels is not None:
            self._draw_label_contours(canvas, labels)

        for m in measurements:
            self._draw_measurement(canvas, m, font_scale)

        if cluster_regions:
            self._draw_cluster_regions(canvas, cluster_regions, font_scale)

        return canvas

    # ── Private ──────────────────────────────────────────────────────────────

    @staticmethod
    def _draw_label_contours(canvas: np.ndarray, labels: np.ndarray) -> None:
        for label_id in range(1, labels.max() + 1):
            mask = (labels == label_id).astype(np.uint8) * 255
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(canvas, contours, -1, _CONTOUR_COLOR, 1)

    @staticmethod
    def _draw_cluster_regions(canvas: np.ndarray, cluster_regions: list, font_scale: float) -> None:
        """Draw semi-transparent red box + '~N grains' label over each unresolved cluster."""
        font = cv2.FONT_HERSHEY_SIMPLEX
        h, w = canvas.shape[:2]

        for cr in cluster_regions:
            x1 = max(0, cr.bbox.x)
            y1 = max(0, cr.bbox.y)
            x2 = min(w, cr.bbox.x + cr.bbox.width)
            y2 = min(h, cr.bbox.y + cr.bbox.height)

            # Semi-transparent red fill
            overlay = canvas.copy()
            cv2.rectangle(overlay, (x1, y1), (x2, y2), _CLUSTER_FILL, -1)
            cv2.addWeighted(overlay, 0.35, canvas, 0.65, 0, canvas)

            # Solid red border (2 px)
            cv2.rectangle(canvas, (x1, y1), (x2, y2), _CLUSTER_BORDER, 2)

            # Label: "~N" centred in the box
            text = f"~{cr.estimated_count}"
            fs = max(font_scale * 1.1, 0.4)
            (tw, th), baseline = cv2.getTextSize(text, font, fs, 2)
            cx = int(cr.centroid_x_px)
            cy = int(cr.centroid_y_px)
            tx = max(x1, min(cx - tw // 2, x2 - tw))
            ty = max(y1 + th, min(cy + th // 2, y2 - baseline))

            # Dark red text background
            cv2.rectangle(canvas,
                          (tx - 2, ty - th - baseline),
                          (tx + tw + 2, ty + baseline),
                          (0, 0, 100), -1)
            cv2.putText(canvas, text, (tx, ty), font, fs,
                        _TEXT_COLOR, 2, cv2.LINE_AA)

    def _draw_measurement(self, canvas: np.ndarray, m: GrainMeasurement, font_scale: float) -> None:
        cx = int(m.centroid_x_px)
        cy = int(m.centroid_y_px)
        h, w = canvas.shape[:2]

        color = _ellipse_color(m)
        is_recovered = getattr(m, "recovered_from_cluster", False)

        half_major = max(int(m.major_axis_px / 2), 1)
        half_minor = max(int(m.minor_axis_px / 2), 1)
        angle = -m.orientation_deg
        thickness = self._thickness + (1 if is_recovered else 0)
        cv2.ellipse(canvas, (cx, cy), (half_major, half_minor),
                    angle, 0, 360, color, thickness)

        if self._show_axes:
            self._draw_axes(canvas, cx, cy, m, w, h)

        cv2.circle(canvas, (cx, cy), max(2, int(half_minor * 0.15)), _CENTROID_COLOR, -1)

        if self._show_ids:
            accent = color if is_recovered else None
            self._put_label(canvas, cx, cy, m, font_scale, w, h, accent)

    def _draw_axes(
        self, canvas: np.ndarray, cx: int, cy: int,
        m: GrainMeasurement, img_w: int, img_h: int,
    ) -> None:
        rad = math.radians(m.orientation_deg)
        cos_a, sin_a = math.cos(rad), math.sin(rad)

        def _clamp(x: int, y: int) -> tuple[int, int]:
            return int(max(0, min(img_w - 1, x))), int(max(0, min(img_h - 1, y)))

        hl = m.major_axis_px / 2
        cv2.line(canvas,
                 _clamp(int(cx + hl * cos_a), int(cy - hl * sin_a)),
                 _clamp(int(cx - hl * cos_a), int(cy + hl * sin_a)),
                 _AXIS_MAJOR_COLOR, 1)

        hw = m.minor_axis_px / 2
        cv2.line(canvas,
                 _clamp(int(cx - hw * sin_a), int(cy - hw * cos_a)),
                 _clamp(int(cx + hw * sin_a), int(cy + hw * cos_a)),
                 _AXIS_MINOR_COLOR, 1)

    def _put_label(
        self, canvas: np.ndarray, cx: int, cy: int,
        m: GrainMeasurement, font_scale: float, img_w: int, img_h: int,
        anomaly_color: tuple | None = None,
    ) -> None:
        half_minor_px = m.minor_axis_px / 2
        font = cv2.FONT_HERSHEY_SIMPLEX

        flag_suffix = " *R" if getattr(m, "recovered_from_cluster", False) else ""

        if self._show_mm:
            text = f"#{m.grain_index} {m.major_axis_mm:.2f}x{m.minor_axis_mm:.2f}mm{flag_suffix}"
        else:
            text = f"#{m.grain_index}{flag_suffix}"

        (tw, th), baseline = cv2.getTextSize(text, font, font_scale, 1)

        if tw > m.major_axis_px * 1.5:
            return

        tx = max(1, min(cx - tw // 2, img_w - tw - 1))
        ty = max(th + 2, min(int(cy - half_minor_px - 3), img_h - baseline - 1))

        bg = _TEXT_BG_RECOVERED if anomaly_color == _CONTOUR_RECOVERED else _TEXT_BG_COLOR
        cv2.rectangle(canvas,
                      (tx - 1, ty - th - baseline),
                      (tx + tw + 1, ty + baseline),
                      bg, -1)
        cv2.putText(canvas, text, (tx, ty), font, font_scale,
                    _TEXT_COLOR, 1, cv2.LINE_AA)
