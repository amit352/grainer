"""Grain quality grading engine.

Takes a list of GrainMeasurement objects + a QualityProfile and produces a
QualityReport with per-grain classification, parameter scores, overall grade,
and a buy/no-buy decision with reasoning.
"""
from __future__ import annotations

import numpy as np

from app.models.domain import GrainMeasurement
from app.models.quality import (
    GrainClass,
    GrainClassification,
    ParameterScore,
    QualityProfile,
    QualityReport,
)


# ── Default profiles ──────────────────────────────────────────────────────────

PROFILES: dict[str, QualityProfile] = {
    "Premium": QualityProfile(
        name="Premium",
        commodity="rice",
        max_total_broken_pct=5.0,
        max_small_broken_pct=2.0,
        min_head_rice_pct=85.0,
        max_length_cv_pct=10.0,
        max_foreign_matter_pct=0.5,
        weight_broken=0.35,
        weight_head_rice=0.25,
        weight_uniformity=0.20,
        weight_foreign_matter=0.10,
        weight_color=0.10,
    ),
    "Rice Standard": QualityProfile(
        name="Rice Standard",
        commodity="rice",
        max_total_broken_pct=15.0,
        max_small_broken_pct=5.0,
        min_head_rice_pct=70.0,
        max_length_cv_pct=15.0,
        max_foreign_matter_pct=1.0,
        weight_broken=0.35,
        weight_head_rice=0.25,
        weight_uniformity=0.20,
        weight_foreign_matter=0.10,
        weight_color=0.10,
    ),
    "Rice Feed Grade": QualityProfile(
        name="Rice Feed Grade",
        commodity="rice",
        max_total_broken_pct=40.0,
        max_small_broken_pct=20.0,
        min_head_rice_pct=40.0,
        max_length_cv_pct=25.0,
        max_foreign_matter_pct=3.0,
        weight_broken=0.30,
        weight_head_rice=0.20,
        weight_uniformity=0.15,
        weight_foreign_matter=0.15,
        weight_color=0.20,
    ),
}

DEFAULT_PROFILE = "Rice Standard"


class QualityService:
    """Classify grains and produce a QualityReport for a scanned lot."""

    @staticmethod
    def assess(
        measurements: list[GrainMeasurement],
        profile: QualityProfile | None = None,
        scan_id: int | None = None,
        lot_id: str = "",
    ) -> QualityReport:
        if profile is None:
            profile = PROFILES[DEFAULT_PROFILE]

        if not measurements:
            return _empty_report(profile, scan_id, lot_id)

        lengths = np.array([m.major_axis_mm for m in measurements])

        # Reference whole-grain length = 75th percentile (robust to broken grain pollution)
        ref_length = float(np.percentile(lengths, 75))

        # ── Classify each grain ───────────────────────────────────────────────
        classifications = [
            _classify(m, ref_length, profile) for m in measurements
        ]

        counts = {cls: 0 for cls in ("whole", "large_broken", "small_broken", "broken", "foreign_matter")}
        for c in classifications:
            counts[c.grain_class] += 1

        n = len(measurements)
        whole_pct        = counts["whole"]          / n * 100
        large_broken_pct = counts["large_broken"]   / n * 100
        small_broken_pct = counts["small_broken"]   / n * 100
        broken_pct       = counts["broken"]         / n * 100
        fm_pct           = counts["foreign_matter"] / n * 100

        total_broken_pct = large_broken_pct + small_broken_pct + broken_pct
        head_rice_pct    = whole_pct

        # CV on whole grains only — fragments and broken pieces inflate variance
        # and mask the true size uniformity of the main crop.
        whole_lengths = np.array([
            m.major_axis_mm for m, c in zip(measurements, classifications)
            if c.grain_class == "whole"
        ])
        if len(whole_lengths) >= 3:
            cv_pct = float(np.std(whole_lengths) / np.mean(whole_lengths) * 100)
        elif np.mean(lengths) > 0:
            cv_pct = float(np.std(lengths) / np.mean(lengths) * 100)
        else:
            cv_pct = 0.0

        # ── Score each parameter 0–10 ─────────────────────────────────────────
        score_broken   = _score_lower(total_broken_pct,  perfect=0,   reject=profile.max_total_broken_pct * 2.5)
        score_head     = _score_higher(head_rice_pct,    perfect=100, reject=profile.min_head_rice_pct * 0.5)
        score_uniform  = _score_lower(cv_pct,            perfect=0,   reject=profile.max_length_cv_pct * 2.5)
        score_fm       = _score_lower(fm_pct,            perfect=0,   reject=profile.max_foreign_matter_pct * 3)

        # Colour scores — not available yet (greyscale scan)
        color_available = False
        score_color = None

        params = [
            ParameterScore(
                name="Broken Grains",
                measured=round(total_broken_pct, 1),
                target=profile.max_total_broken_pct,
                unit="%",
                score=score_broken,
                status=_status(total_broken_pct, profile.max_total_broken_pct,
                               profile.max_total_broken_pct * 1.5),
                note=f"Large: {large_broken_pct:.1f}%  Small+: {small_broken_pct + broken_pct:.1f}%",
            ),
            ParameterScore(
                name="Head Rice (Whole)",
                measured=round(head_rice_pct, 1),
                target=profile.min_head_rice_pct,
                unit="%",
                score=score_head,
                status=_status_min(head_rice_pct, profile.min_head_rice_pct,
                                   profile.min_head_rice_pct * 0.75),
            ),
            ParameterScore(
                name="Size Uniformity (CV)",
                measured=round(cv_pct, 1),
                target=profile.max_length_cv_pct,
                unit="%",
                score=score_uniform,
                status=_status(cv_pct, profile.max_length_cv_pct,
                               profile.max_length_cv_pct * 2.0),
                note="Lower is better",
            ),
            ParameterScore(
                name="Foreign Matter",
                measured=round(fm_pct, 1),
                target=profile.max_foreign_matter_pct,
                unit="%",
                score=score_fm,
                status=_status(fm_pct, profile.max_foreign_matter_pct,
                               profile.max_foreign_matter_pct * 3),
            ),
        ]

        # Weighted total — adjust weights when colour is unavailable
        if color_available and score_color is not None:
            w_sum = (profile.weight_broken + profile.weight_head_rice +
                     profile.weight_uniformity + profile.weight_foreign_matter +
                     profile.weight_color)
            total = (
                score_broken  * profile.weight_broken +
                score_head    * profile.weight_head_rice +
                score_uniform * profile.weight_uniformity +
                score_fm      * profile.weight_foreign_matter +
                score_color   * profile.weight_color
            ) / w_sum * 10
        else:
            w_sum = (profile.weight_broken + profile.weight_head_rice +
                     profile.weight_uniformity + profile.weight_foreign_matter)
            total = (
                score_broken  * profile.weight_broken +
                score_head    * profile.weight_head_rice +
                score_uniform * profile.weight_uniformity +
                score_fm      * profile.weight_foreign_matter
            ) / w_sum * 10

        total = max(0.0, min(100.0, round(total, 1)))
        grade, decision, recommendation = _grade(total, params, profile)

        return QualityReport(
            scan_id=scan_id,
            lot_id=lot_id,
            profile_name=profile.name,
            grain_count=n,
            whole_count=counts["whole"],
            large_broken_count=counts["large_broken"],
            small_broken_count=counts["small_broken"],
            broken_count=counts["broken"],
            foreign_matter_count=counts["foreign_matter"],
            head_rice_pct=round(head_rice_pct, 1),
            large_broken_pct=round(large_broken_pct, 1),
            small_broken_pct=round(small_broken_pct, 1),
            total_broken_pct=round(total_broken_pct, 1),
            foreign_matter_pct=round(fm_pct, 1),
            length_cv_pct=round(cv_pct, 1),
            reference_length_mm=round(ref_length, 2),
            parameters=params,
            total_score=total,
            grade=grade,
            decision=decision,
            recommendation=recommendation,
            classifications=classifications,
        )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _classify(
    m: GrainMeasurement,
    ref_length: float,
    profile: QualityProfile,
) -> GrainClassification:
    ratio = m.major_axis_mm / ref_length if ref_length > 0 else 1.0

    # Foreign matter: small, round, solid object (pebble, weed seed, husk fragment).
    # Must be SHORT (< 30% of ref grain) — large compact blobs are merged grain clusters,
    # not foreign matter, and should be counted as broken/oversized instead.
    if ratio < 0.30 and m.aspect_ratio < 1.8 and (m.solidity is not None and m.solidity > 0.88):
        cls: GrainClass = "foreign_matter"
    elif ratio >= 0.75:
        cls = "whole"
    elif ratio >= 0.50:
        cls = "large_broken"
    elif ratio >= 0.25:
        cls = "small_broken"
    else:
        cls = "broken"

    return GrainClassification(
        grain_index=m.grain_index,
        major_axis_mm=round(m.major_axis_mm, 2),
        grain_class=cls,
        length_ratio=round(ratio, 3),
    )


def _score_lower(value: float, perfect: float, reject: float) -> float:
    """Score a parameter where lower value is better. Returns 0–10."""
    if reject <= perfect:
        return 10.0
    ratio = (value - perfect) / (reject - perfect)
    return round(max(0.0, min(10.0, (1 - ratio) * 10)), 2)


def _score_higher(value: float, perfect: float, reject: float) -> float:
    """Score a parameter where higher value is better. Returns 0–10."""
    if perfect <= reject:
        return 10.0
    ratio = (perfect - value) / (perfect - reject)
    return round(max(0.0, min(10.0, (1 - ratio) * 10)), 2)


def _status(value: float, warn_at: float, fail_at: float) -> str:
    if value <= warn_at:
        return "pass"
    if value <= fail_at:
        return "warn"
    return "fail"


def _status_min(value: float, warn_at: float, fail_at: float) -> str:
    if value >= warn_at:
        return "pass"
    if value >= fail_at:
        return "warn"
    return "fail"


def _grade(
    score: float,
    params: list[ParameterScore],
    profile: QualityProfile,
) -> tuple[str, str, str]:
    fail_params = [p for p in params if p.status == "fail"]
    warn_params = [p for p in params if p.status == "warn"]

    if score >= 85 and not fail_params:
        grade, decision = "A", "Buy"
        reason = (
            f"Premium quality — score {score}/100. "
            f"All parameters within spec for {profile.name}."
        )
    elif score >= 70 and len(fail_params) == 0:
        grade, decision = "B", "Buy – Negotiate Price"
        if warn_params:
            names = ", ".join(p.name for p in warn_params)
            reason = (
                f"Standard quality — score {score}/100. "
                f"{names} slightly below premium spec. "
                "Accept at market price or negotiate a small discount."
            )
        else:
            reason = f"Good quality — score {score}/100. Meets {profile.name} standard."
    elif score >= 55 and len(fail_params) <= 1:
        grade, decision = "C", "Conditional – Discount Required"
        names = ", ".join(p.name for p in fail_params + warn_params)
        reason = (
            f"Below standard — score {score}/100. "
            f"Issues: {names}. "
            "Suitable for processed product or milling at a significant discount."
        )
    else:
        grade, decision = "Reject", "Do Not Buy"
        names = ", ".join(p.name for p in fail_params)
        reason = (
            f"Unacceptable quality — score {score}/100. "
            f"Failed parameters: {names}. "
            "Does not meet minimum requirements for any grade."
        )

    return grade, decision, reason


def _empty_report(profile: QualityProfile, scan_id, lot_id) -> QualityReport:
    return QualityReport(
        scan_id=scan_id, lot_id=lot_id, profile_name=profile.name,
        grain_count=0, whole_count=0, large_broken_count=0,
        small_broken_count=0, broken_count=0, foreign_matter_count=0,
        head_rice_pct=0, large_broken_pct=0, small_broken_pct=0,
        total_broken_pct=0, foreign_matter_pct=0, length_cv_pct=0,
        reference_length_mm=0,
        parameters=[], total_score=0, grade="Reject",
        decision="Do Not Buy", recommendation="No grains detected.",
        classifications=[],
    )
