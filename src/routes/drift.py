import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.core.security import require_client_key
from src.database import get_db
from src.models.db_models import ApiKey, TelemetrySnapshot
from src.services.drift_detection_service import evaluate_telemetry_drift, DriftReport

router = APIRouter(prefix="/v1/drift", tags=["Drift Analysis"])


@router.get("/report", response_model=DriftReport)
def get_drift_report(
    target_api_key_hash: Optional[str] = Query(default=None),
    baseline_limit: int = Query(default=10, ge=1, le=100),
    target_limit: int = Query(default=10, ge=1, le=100),
    api_key: ApiKey = Depends(require_client_key),
    db: Session = Depends(get_db),
):
    """Calculate statistical telemetry drift without raw text or identifiers.
    
    Splits recent telemetry snapshots into baseline (older) and target (newer)
    windows and runs PSI and k-anonymity analysis.
    """
    key_hash_to_query = api_key.key_hash
    if target_api_key_hash and target_api_key_hash != api_key.key_hash:
        if api_key.scope != "admin":
            raise HTTPException(status_code=403, detail="Unauthorized for requested api_key_hash")
        key_hash_to_query = target_api_key_hash

    snapshots = (
        db.query(TelemetrySnapshot)
        .filter(TelemetrySnapshot.api_key_hash == key_hash_to_query)
        .order_by(TelemetrySnapshot.created_at.desc())
        .limit(baseline_limit + target_limit)
        .all()
    )

    if not snapshots:
        return evaluate_telemetry_drift(
            tenant_id=key_hash_to_query[:16],
            baseline_payloads=[],
            target_payloads=[],
        )

    parsed_payloads = []
    for s in snapshots:
        parsed_payloads.append({
            "riskCounts": {
                "LOW": s.low_count,
                "MEDIUM": s.medium_count,
                "HIGH": s.high_count,
                "CRITICAL": s.critical_count,
            },
            "resolutions": {
                "local": s.local_resolutions,
                "apiEscalations": s.api_escalations,
                "cachedApiVerdicts": s.cached_api_verdicts,
            },
            "shadow": {
                "agreements": s.shadow_agreements,
                "disagreements": s.shadow_disagreements,
            },
        })

    # Split into target (recent) and baseline (older)
    half = len(parsed_payloads) // 2
    target_slice = parsed_payloads[:half] if half > 0 else parsed_payloads
    baseline_slice = parsed_payloads[half:] if half > 0 else []

    return evaluate_telemetry_drift(
        tenant_id=key_hash_to_query[:16],
        baseline_payloads=baseline_slice,
        target_payloads=target_slice,
    )
