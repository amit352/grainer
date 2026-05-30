"""CSV and PDF export from scan results."""
from __future__ import annotations

import io
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger

from app.database.models import Grain, Scan
from app.models.domain import ScanStatistics


_CSV_COLUMNS = [
    "grain_index",
    "major_axis_mm",
    "minor_axis_mm",
    "area_mm2",
    "perimeter_mm",
    "aspect_ratio",
    "orientation_deg",
    "solidity",
    "eccentricity",
    "centroid_x_mm",
    "centroid_y_mm",
    "area_px",
    "major_axis_px",
    "minor_axis_px",
    "bbox_x",
    "bbox_y",
    "bbox_w",
    "bbox_h",
]


class ExportService:

    @staticmethod
    def grains_to_dataframe(grains: list[Grain]) -> pd.DataFrame:
        rows = [
            {
                "grain_index": g.grain_index,
                "major_axis_mm": round(g.major_axis_mm, 4),
                "minor_axis_mm": round(g.minor_axis_mm, 4),
                "area_mm2": round(g.area_mm2, 4),
                "perimeter_mm": round(g.perimeter_mm, 4),
                "aspect_ratio": round(g.aspect_ratio, 3),
                "orientation_deg": round(g.orientation_deg, 2),
                "solidity": round(g.solidity, 4) if g.solidity is not None else None,
                "eccentricity": round(g.eccentricity, 4) if g.eccentricity is not None else None,
                "centroid_x_mm": round(g.centroid_x_mm, 3),
                "centroid_y_mm": round(g.centroid_y_mm, 3),
                "area_px": int(g.area_px),
                "major_axis_px": round(g.major_axis_px, 2),
                "minor_axis_px": round(g.minor_axis_px, 2),
                "bbox_x": g.bbox_x,
                "bbox_y": g.bbox_y,
                "bbox_w": g.bbox_w,
                "bbox_h": g.bbox_h,
            }
            for g in sorted(grains, key=lambda g: g.grain_index)
        ]
        return pd.DataFrame(rows, columns=_CSV_COLUMNS)

    @staticmethod
    def to_csv_bytes(grains: list[Grain]) -> bytes:
        df = ExportService.grains_to_dataframe(grains)
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        return buf.getvalue().encode("utf-8")

    @staticmethod
    def to_pdf_bytes(
        scan: Scan,
        grains: list[Grain],
        stats: ScanStatistics,
        annotated_image_path: Optional[str] = None,
    ) -> bytes:
        """Generate a multi-page PDF report using reportlab."""
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import (
                Image,
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
        except ImportError:
            raise RuntimeError("reportlab is required for PDF export. Run: pip install reportlab")

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm)
        styles = getSampleStyleSheet()
        story = []

        # ── Page 1: Summary ────────────────────────────────────────────────────
        story.append(Paragraph("<b>Grain Scanner Report</b>", styles["Title"]))
        story.append(Spacer(1, 6 * mm))

        meta_data = [
            ["File", scan.filename],
            ["Processed", scan.processed_at.strftime("%Y-%m-%d %H:%M:%S") if scan.processed_at else "—"],
            ["DPI", str(scan.dpi)],
            ["Image size", f"{scan.width_mm:.1f} × {scan.height_mm:.1f} mm ({scan.width_px}×{scan.height_px} px)"],
            ["Grain count", str(scan.grain_count or 0)],
            ["Processing time", f"{scan.processing_time_s:.2f} s" if scan.processing_time_s else "—"],
        ]
        story.append(_make_table(meta_data, col_widths=[60 * mm, 110 * mm]))
        story.append(Spacer(1, 8 * mm))

        story.append(Paragraph("<b>Statistics Summary</b>", styles["Heading2"]))
        stats_data = [
            ["Metric", "Mean", "Std Dev", "Min", "Max"],
            ["Major Axis (mm)",
             f"{stats.mean_major_axis_mm:.3f}", f"{stats.std_major_axis_mm:.3f}",
             f"{stats.min_major_axis_mm:.3f}", f"{stats.max_major_axis_mm:.3f}"],
            ["Minor Axis (mm)",
             f"{stats.mean_minor_axis_mm:.3f}", f"{stats.std_minor_axis_mm:.3f}",
             f"{stats.min_minor_axis_mm:.3f}", f"{stats.max_minor_axis_mm:.3f}"],
            ["Area (mm²)",
             f"{stats.mean_area_mm2:.3f}", f"{stats.std_area_mm2:.3f}",
             f"{stats.min_area_mm2:.3f}", f"{stats.max_area_mm2:.3f}"],
            ["Aspect Ratio",
             f"{stats.mean_aspect_ratio:.3f}", f"{stats.std_aspect_ratio:.3f}", "—", "—"],
        ]
        story.append(_make_table(stats_data, header=True))
        story.append(Spacer(1, 8 * mm))

        # ── Annotated image ────────────────────────────────────────────────────
        if annotated_image_path and Path(annotated_image_path).exists():
            story.append(Paragraph("<b>Annotated Scan</b>", styles["Heading2"]))
            story.append(Spacer(1, 3 * mm))
            img = Image(annotated_image_path, width=170 * mm, height=120 * mm, kind="proportional")
            story.append(img)
            story.append(Spacer(1, 6 * mm))

        # ── Per-grain table (paginated at 50 rows) ─────────────────────────────
        story.append(Paragraph("<b>Per-Grain Measurements</b>", styles["Heading2"]))
        df = ExportService.grains_to_dataframe(grains)
        display_cols = ["grain_index", "major_axis_mm", "minor_axis_mm", "area_mm2", "aspect_ratio", "orientation_deg"]
        header = [["#", "L (mm)", "W (mm)", "Area (mm²)", "Aspect", "Angle°"]]
        chunk_size = 50
        for start in range(0, len(df), chunk_size):
            chunk = df[display_cols].iloc[start:start + chunk_size]
            table_data = header + chunk.values.tolist()
            story.append(_make_table(table_data, header=True, col_widths=[15*mm, 30*mm, 30*mm, 30*mm, 25*mm, 25*mm]))
            story.append(Spacer(1, 4 * mm))

        doc.build(story)
        return buf.getvalue()


    @staticmethod
    def to_coa_pdf_bytes(
        quality_report: dict,
        scan_filename: str = "",
        annotated_image_path: Optional[str] = None,
    ) -> bytes:
        """Generate a single-page Certificate of Analysis PDF."""
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import mm
            from reportlab.lib.enums import TA_CENTER, TA_LEFT
            from reportlab.platypus import (
                Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
                HRFlowable,
            )
        except ImportError:
            raise RuntimeError("reportlab is required for PDF export. Run: pip install reportlab")

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            topMargin=12 * mm, bottomMargin=12 * mm,
            leftMargin=15 * mm, rightMargin=15 * mm,
        )
        styles = getSampleStyleSheet()
        W = A4[0] - 30 * mm  # usable width

        grade_hex = {"A": "#00aa44", "B": "#1a7abf", "C": "#cc8800", "Reject": "#cc2222"}
        grade = quality_report.get("grade", "?")
        score = quality_report.get("total_score", 0)
        decision = quality_report.get("decision", "")
        recommendation = quality_report.get("recommendation", "")
        lot_id = quality_report.get("lot_id", "") or "—"
        profile_name = quality_report.get("profile_name", "—")
        grain_count = quality_report.get("grain_count", 0)
        ref_len = quality_report.get("reference_length_mm", 0)
        g_color = colors.HexColor(grade_hex.get(grade, "#555555"))

        story = []

        # ── Header ────────────────────────────────────────────────────────────
        hdr_style = ParagraphStyle("hdr", fontSize=18, fontName="Helvetica-Bold",
                                   textColor=colors.HexColor("#1a3a5c"), alignment=TA_CENTER)
        sub_style = ParagraphStyle("sub", fontSize=10, fontName="Helvetica",
                                   textColor=colors.HexColor("#555555"), alignment=TA_CENTER)
        story.append(Paragraph("CERTIFICATE OF ANALYSIS", hdr_style))
        story.append(Paragraph("Grain Quality Assessment Report", sub_style))
        story.append(Spacer(1, 4 * mm))
        story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a3a5c")))
        story.append(Spacer(1, 3 * mm))

        # ── Meta table ────────────────────────────────────────────────────────
        processed_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        meta = [
            ["Lot ID", lot_id, "Date", processed_at],
            ["File", scan_filename or "—", "Profile", profile_name],
            ["Grain Count", str(grain_count), "Ref. Length", f"{ref_len:.2f} mm"],
        ]
        meta_tbl = Table(meta, colWidths=[25*mm, 60*mm, 30*mm, 60*mm])
        meta_tbl.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1a3a5c")),
            ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#1a3a5c")),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(meta_tbl)
        story.append(Spacer(1, 4 * mm))

        # ── Grade banner ──────────────────────────────────────────────────────
        banner_data = [[
            Paragraph(
                f'<font size="20" color="{grade_hex.get(grade, "#555")}">'
                f'<b>Grade {grade}</b></font>'
                f'&nbsp;&nbsp;·&nbsp;&nbsp;'
                f'<font size="16" color="#333333">{score}/100</font>',
                ParagraphStyle("bn", alignment=TA_CENTER)
            ),
        ]]
        banner_tbl = Table(banner_data, colWidths=[W])
        banner_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(grade_hex.get(grade, "#555555") + "22")),
            ("BOX", (0, 0), (-1, -1), 2, g_color),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]))
        story.append(banner_tbl)

        # Decision line
        dec_style = ParagraphStyle("dec", fontSize=10, fontName="Helvetica-Bold",
                                   textColor=g_color, alignment=TA_CENTER, spaceBefore=4)
        story.append(Paragraph(decision, dec_style))
        rec_style = ParagraphStyle("rec", fontSize=8, fontName="Helvetica",
                                   textColor=colors.HexColor("#555555"), alignment=TA_CENTER)
        story.append(Paragraph(recommendation, rec_style))
        story.append(Spacer(1, 4 * mm))

        # ── Parameter table ───────────────────────────────────────────────────
        story.append(Paragraph(
            "QUALITY PARAMETERS",
            ParagraphStyle("sh", fontSize=9, fontName="Helvetica-Bold",
                           textColor=colors.HexColor("#1a3a5c"))
        ))
        story.append(Spacer(1, 1 * mm))

        status_labels = {"pass": "PASS", "warn": "CAUTION", "fail": "FAIL"}
        status_colors = {
            "pass": colors.HexColor("#007733"),
            "warn": colors.HexColor("#cc8800"),
            "fail": colors.HexColor("#cc2222"),
        }

        param_data = [["Parameter", "Measured", "Target", "Score", "Status"]]
        params = quality_report.get("parameters", [])
        for p in params:
            param_data.append([
                p["name"],
                f"{p['measured']}{p['unit']}",
                f"{p['target']}{p['unit']}",
                f"{p['score']}/10",
                status_labels.get(p["status"], p["status"].upper()),
            ])

        param_tbl = Table(param_data, colWidths=[55*mm, 30*mm, 30*mm, 25*mm, 35*mm])
        param_style = [
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for row_idx, p in enumerate(params, start=1):
            col = status_colors.get(p["status"], colors.black)
            param_style += [
                ("TEXTCOLOR", (4, row_idx), (4, row_idx), col),
                ("FONTNAME", (4, row_idx), (4, row_idx), "Helvetica-Bold"),
            ]
        param_tbl.setStyle(TableStyle(param_style))
        story.append(param_tbl)
        story.append(Spacer(1, 4 * mm))

        # ── Grain classification breakdown ────────────────────────────────────
        story.append(Paragraph(
            "GRAIN CLASSIFICATION",
            ParagraphStyle("sh2", fontSize=9, fontName="Helvetica-Bold",
                           textColor=colors.HexColor("#1a3a5c"))
        ))
        story.append(Spacer(1, 1 * mm))

        cls_data = [
            ["Whole (Head Rice)", "Large Broken", "Small Broken", "Broken", "Foreign Matter"],
            [
                f"{quality_report.get('whole_count', 0)}  ({quality_report.get('head_rice_pct', 0):.1f}%)",
                f"{quality_report.get('large_broken_count', 0)}  ({quality_report.get('large_broken_pct', 0):.1f}%)",
                f"{quality_report.get('small_broken_count', 0)}  ({quality_report.get('small_broken_pct', 0):.1f}%)",
                f"{quality_report.get('broken_count', 0)}  ({quality_report.get('total_broken_pct', 0) - quality_report.get('large_broken_pct', 0) - quality_report.get('small_broken_pct', 0):.1f}%)",
                f"{quality_report.get('foreign_matter_count', 0)}  ({quality_report.get('foreign_matter_pct', 0):.1f}%)",
            ],
        ]
        cls_tbl = Table(cls_data, colWidths=[W / 5] * 5)
        cls_tbl.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f0e8")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(cls_tbl)

        # ── Annotated image (if available) ────────────────────────────────────
        if annotated_image_path and Path(annotated_image_path).exists():
            story.append(Spacer(1, 4 * mm))
            story.append(Paragraph(
                "SCAN IMAGE",
                ParagraphStyle("sh3", fontSize=9, fontName="Helvetica-Bold",
                               textColor=colors.HexColor("#1a3a5c"))
            ))
            story.append(Spacer(1, 1 * mm))
            img = Image(annotated_image_path, width=W, height=60 * mm, kind="proportional")
            story.append(img)

        # ── Footer ────────────────────────────────────────────────────────────
        story.append(Spacer(1, 4 * mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
        story.append(Spacer(1, 2 * mm))
        footer_style = ParagraphStyle("ft", fontSize=7, fontName="Helvetica",
                                      textColor=colors.grey, alignment=TA_CENTER)
        story.append(Paragraph(
            "This certificate is generated by Grain Scanner and is based on computer vision analysis. "
            "Results are indicative and should be verified by an accredited laboratory for regulatory purposes.",
            footer_style,
        ))

        doc.build(story)
        return buf.getvalue()


def _make_table(data: list, header: bool = False, col_widths=None):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    tbl = Table(data, colWidths=col_widths)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.whitesmoke, colors.white]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    tbl.setStyle(TableStyle(style))
    return tbl
