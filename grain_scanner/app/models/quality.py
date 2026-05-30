"""Quality grading models — profiles, per-grain classification, lot report."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


GrainClass = Literal["whole", "large_broken", "small_broken", "broken", "foreign_matter"]

GRADE = Literal["A", "B", "C", "Reject"]
DECISION = Literal["Buy", "Buy – Negotiate Price", "Conditional – Discount Required", "Do Not Buy"]


class QualityProfile(BaseModel):
    """Configurable thresholds for one commodity / buyer standard."""

    name: str = "Default Rice"
    commodity: str = "rice"

    # ── Broken grain limits (%) ───────────────────────────────────────────────
    # Reference length = 75th percentile of major_axis_mm in the lot.
    # whole        : length >= 75% of reference
    # large_broken : 50–75% of reference
    # small_broken : 25–50% of reference
    # broken       : < 25% of reference
    max_total_broken_pct: float = Field(15.0, description="Max % broken (all sizes)")
    max_small_broken_pct: float = Field(5.0,  description="Max % small+broken")

    # ── Whole grain (head rice) ───────────────────────────────────────────────
    min_head_rice_pct: float = Field(70.0, description="Min % whole grains")

    # ── Size uniformity ───────────────────────────────────────────────────────
    max_length_cv_pct: float = Field(15.0, description="Max CV% of grain length")

    # ── Foreign matter ────────────────────────────────────────────────────────
    max_foreign_matter_pct: float = Field(1.0, description="Max % foreign matter")

    # ── Color (populated only when color scan available) ─────────────────────
    min_whiteness_L: Optional[float] = Field(None, description="Min CIE L* (brightness)")
    max_yellowness_b: Optional[float] = Field(None, description="Max CIE b* (yellowness)")

    # ── Scoring weights (must sum ≈ 1.0) ─────────────────────────────────────
    weight_broken: float = 0.35
    weight_head_rice: float = 0.25
    weight_uniformity: float = 0.20
    weight_foreign_matter: float = 0.10
    weight_color: float = 0.10          # only counted when color data available


class GrainClassification(BaseModel):
    """Broken-grain classification result for a single grain."""

    grain_index: int
    major_axis_mm: float
    grain_class: GrainClass
    length_ratio: float = Field(..., description="grain length ÷ reference whole-grain length")


class ParameterScore(BaseModel):
    """Score and status for one quality parameter."""

    name: str
    measured: float
    target: float
    unit: str
    score: float = Field(..., ge=0.0, le=10.0)
    status: Literal["pass", "warn", "fail"]
    note: str = ""


class QualityReport(BaseModel):
    """Full quality assessment for one scanned lot."""

    # ── Identity ──────────────────────────────────────────────────────────────
    scan_id: Optional[int] = None
    lot_id: str = ""
    profile_name: str
    grain_count: int

    # ── Classification counts ─────────────────────────────────────────────────
    whole_count: int
    large_broken_count: int
    small_broken_count: int
    broken_count: int
    foreign_matter_count: int

    # ── Percentages ───────────────────────────────────────────────────────────
    head_rice_pct: float
    large_broken_pct: float
    small_broken_pct: float
    total_broken_pct: float
    foreign_matter_pct: float
    length_cv_pct: float

    # ── Reference grain length used for classification ────────────────────────
    reference_length_mm: float

    # ── Per-parameter scores ──────────────────────────────────────────────────
    parameters: list[ParameterScore]

    # ── Overall ───────────────────────────────────────────────────────────────
    total_score: float = Field(..., ge=0.0, le=100.0)
    grade: GRADE
    decision: DECISION
    recommendation: str           # human-readable explanation

    # ── Per-grain detail ──────────────────────────────────────────────────────
    classifications: list[GrainClassification]


class LotHistorySummary(BaseModel):
    """Lightweight quality summary for a single scan — used in trend views."""

    scan_id: int
    filename: str
    processed_at: Optional[str] = None
    lot_id: str = ""
    profile_name: str
    grain_count: int
    grade: GRADE
    total_score: float
    head_rice_pct: float
    total_broken_pct: float
    foreign_matter_pct: float
    decision: DECISION
