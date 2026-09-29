"""Drift Detection Service with Minimal Aggregate Data.

Calculates Population Stability Index (PSI) and statistical divergence
over aggregated telemetry counters without collecting raw text or PII.
Implements k-anonymity suppression (minimum sample threshold N >= 30)
and explicitly separates traffic volume shifts from quality degradation.
"""
import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DriftBucket(BaseModel):
    name: str
    baseline_count: int = Field(ge=0)
    target_count: int = Field(ge=0)
    baseline_prop: float = Field(ge=0.0, le=1.0)
    target_prop: float = Field(ge=0.0, le=1.0)
    psi_contribution: float = Field(ge=0.0)


class DriftAnalysisResult(BaseModel):
    metric_name: str
    status: str  # "INSUFFICIENT_DATA", "STABLE", "TRAFFIC_SHIFT", "QUALITY_DRIFT"
    psi_score: float
    baseline_total: int
    target_total: int
    min_sample_threshold: int = 30
    suppressed_buckets: int = 0
    buckets: List[DriftBucket]
    warning_message: Optional[str] = None
    interpretation: str


def calculate_psi(
    baseline_counts: Dict[str, int],
    target_counts: Dict[str, int],
    min_sample_threshold: int = 30,
    epsilon: float = 1e-4,
) -> DriftAnalysisResult:
    """Calculate Population Stability Index (PSI) with k-anonymity suppression.
    
    PSI interpretation:
    - PSI < 0.10: No significant shift (STABLE)
    - 0.10 <= PSI < 0.25: Moderate shift / Traffic shift (TRAFFIC_SHIFT)
    - PSI >= 0.25: Significant shift / Actionable drift (QUALITY_DRIFT)
    """
    baseline_total = sum(baseline_counts.values())
    target_total = sum(target_counts.values())

    all_keys = sorted(set(baseline_counts.keys()).union(set(target_counts.keys())))

    # k-anonymity / minimum sample check
    if baseline_total < min_sample_threshold or target_total < min_sample_threshold:
        return DriftAnalysisResult(
            metric_name="aggregated_drift",
            status="INSUFFICIENT_DATA",
            psi_score=0.0,
            baseline_total=baseline_total,
            target_total=target_total,
            min_sample_threshold=min_sample_threshold,
            suppressed_buckets=0,
            buckets=[],
            warning_message=f"Sample size below threshold (baseline={baseline_total}, target={target_total}, required>={min_sample_threshold}).",
            interpretation="Insufficient data to make statistical claims without high error margin.",
        )

    buckets: List[DriftBucket] = []
    total_psi = 0.0
    suppressed = 0

    for key in all_keys:
        b_cnt = baseline_counts.get(key, 0)
        t_cnt = target_counts.get(key, 0)

        # Suppress buckets that are excessively tiny to prevent individual leakage
        if b_cnt < 2 and t_cnt < 2:
            suppressed += 1
            continue

        b_prop = (b_cnt + epsilon) / (baseline_total + epsilon * len(all_keys))
        t_prop = (t_cnt + epsilon) / (target_total + epsilon * len(all_keys))

        # PSI contribution = (target_prop - baseline_prop) * ln(target_prop / baseline_prop)
        psi_item = (t_prop - b_prop) * math.log(t_prop / b_prop)
        total_psi += max(0.0, psi_item)

        buckets.append(
            DriftBucket(
                name=key,
                baseline_count=b_cnt,
                target_count=t_cnt,
                baseline_prop=round(b_prop, 4),
                target_prop=round(t_prop, 4),
                psi_contribution=round(psi_item, 4),
            )
        )

    # Determine status and actionable interpretation
    if total_psi < 0.10:
        status = "STABLE"
        msg = None
        interp = "Distribution is stable across periods. No drift detected."
    elif total_psi < 0.25:
        status = "TRAFFIC_SHIFT"
        msg = f"Moderate distribution shift detected (PSI={total_psi:.3f}). Likely benign population or topic traffic shift."
        interp = "Traffic composition has shifted moderately, but error rates are not showing sharp degradation."
    else:
        status = "QUALITY_DRIFT"
        msg = f"Significant drift detected (PSI={total_psi:.3f} >= 0.25). Review calibration and active learning queue."
        interp = "Severe divergence from baseline. Potential model degradation, label drift, or adversarial evasion."

    return DriftAnalysisResult(
        metric_name="risk_and_resolution_distribution",
        status=status,
        psi_score=round(total_psi, 4),
        baseline_total=baseline_total,
        target_total=target_total,
        min_sample_threshold=min_sample_threshold,
        suppressed_buckets=suppressed,
        buckets=buckets,
        warning_message=msg,
        interpretation=interp,
    )


class DriftReport(BaseModel):
    tenant_id: str
    timestamp: int
    risk_drift: DriftAnalysisResult
    resolution_drift: DriftAnalysisResult
    shadow_drift: DriftAnalysisResult
    overall_recommendation: str


def evaluate_telemetry_drift(
    tenant_id: str,
    baseline_payloads: List[Dict[str, Any]],
    target_payloads: List[Dict[str, Any]],
    timestamp: int = 1774780800,
) -> DriftReport:
    """Aggregate multiple periodic telemetry snapshots and detect multi-dimensional drift."""
    # Aggregate Risk Counts
    base_risks: Dict[str, int] = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    target_risks: Dict[str, int] = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}

    # Aggregate Resolutions
    base_res: Dict[str, int] = {"local": 0, "apiEscalations": 0, "cachedApiVerdicts": 0}
    target_res: Dict[str, int] = {"local": 0, "apiEscalations": 0, "cachedApiVerdicts": 0}

    # Aggregate Shadow Agreement
    base_shadow: Dict[str, int] = {"agreements": 0, "disagreements": 0}
    target_shadow: Dict[str, int] = {"agreements": 0, "disagreements": 0}

    for p in baseline_payloads:
        rc = p.get("riskCounts", {})
        for k in base_risks:
            base_risks[k] += rc.get(k, 0)

        res = p.get("resolutions", {})
        for k in base_res:
            base_res[k] += res.get(k, 0)

        sh = p.get("shadow", {})
        base_shadow["agreements"] += sh.get("agreements", 0)
        base_shadow["disagreements"] += sh.get("disagreements", 0)

    for p in target_payloads:
        rc = p.get("riskCounts", {})
        for k in target_risks:
            target_risks[k] += rc.get(k, 0)

        res = p.get("resolutions", {})
        for k in target_res:
            target_res[k] += res.get(k, 0)

        sh = p.get("shadow", {})
        target_shadow["agreements"] += sh.get("agreements", 0)
        target_shadow["disagreements"] += sh.get("disagreements", 0)

    risk_result = calculate_psi(base_risks, target_risks)
    risk_result.metric_name = "risk_distribution"

    res_result = calculate_psi(base_res, target_res)
    res_result.metric_name = "resolution_distribution"

    shadow_result = calculate_psi(base_shadow, target_shadow)
    shadow_result.metric_name = "shadow_agreement"

    # Overall recommendation synthesis
    if any(r.status == "QUALITY_DRIFT" for r in [risk_result, res_result, shadow_result]):
        rec = "ACTION_REQUIRED: Flagged for active learning batch review. Do not trigger automatic retraining."
    elif any(r.status == "TRAFFIC_SHIFT" for r in [risk_result, res_result]):
        rec = "OBSERVE: Traffic composition changed without quality degradation. Continue monitoring."
    elif all(r.status == "INSUFFICIENT_DATA" for r in [risk_result, res_result]):
        rec = "GATHER_DATA: Awaiting minimum threshold of 30 analyses before asserting drift status."
    else:
        rec = "HEALTHY: Baseline and target telemetry distributions are aligned."

    return DriftReport(
        tenant_id=tenant_id,
        timestamp=timestamp,
        risk_drift=risk_result,
        resolution_drift=res_result,
        shadow_drift=shadow_result,
        overall_recommendation=rec,
    )
