import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security, status
from fastapi.security import APIKeyHeader
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.core.security import require_client_key
from src.database import get_db
from src.models.db_models import ApiKey, TelemetrySnapshot
from src.models.telemetry import TelemetryPayload
from src.services.telemetry_token import TOKEN_TTL_SECONDS, issue_telemetry_token, verify_telemetry_token

router = APIRouter()
telemetry_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_telemetry_key(
    header_key: str | None = Security(telemetry_api_key_header),
    telemetry_token: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> ApiKey:
    """Acepta header normal o token efímero; nunca una API key larga en la URL."""
    if header_key:
        from src.core.security import hash_api_key

        key_hash = hash_api_key(header_key)
    elif telemetry_token:
        key_hash = verify_telemetry_token(telemetry_token)
        if key_hash is None:
            raise HTTPException(status_code=401, detail="Invalid telemetry token")
    else:
        raise HTTPException(status_code=401, detail="Telemetry authentication missing")

    api_key = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if api_key is None or api_key.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    api_key.last_used_at = int(time.time())
    db.commit()
    return api_key


@router.post("/token")
def create_telemetry_token(api_key: ApiKey = Depends(require_client_key)):
    token, expires_at = issue_telemetry_token(api_key.key_hash)
    return {
        "success": True,
        "data": {
            "token": token,
            "expires_at": expires_at,
            "expires_in": TOKEN_TTL_SECONDS,
        },
    }


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def ingest_telemetry(
    request: Request,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_telemetry_key),
):
    try:
        payload = TelemetryPayload.model_validate_json(await request.body())
    except ValidationError as exc:
        safe_errors = [
            {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        raise HTTPException(status_code=422, detail=safe_errors) from exc

    now = int(time.time())
    interventions = payload.interventions
    snapshot = TelemetrySnapshot(
        id=str(uuid.uuid4()),
        api_key_hash=api_key.key_hash,
        created_at=now,
        purge_at=now + (90 * 24 * 60 * 60),
        total_analyses=payload.totalAnalyses,
        low_count=payload.riskCounts.LOW,
        medium_count=payload.riskCounts.MEDIUM,
        high_count=payload.riskCounts.HIGH,
        critical_count=payload.riskCounts.CRITICAL,
        v3_term_counts=json.dumps(payload.topV3Terms, sort_keys=True),
        api_escalations=payload.resolutions.apiEscalations,
        local_resolutions=payload.resolutions.local,
        cached_api_verdicts=payload.resolutions.cachedApiVerdicts,
        shadow_agreements=payload.shadow.agreements,
        shadow_disagreements=payload.shadow.disagreements,
        shadow_model_counts=json.dumps(
            {
                model_id: counts.model_dump()
                for model_id, counts in payload.shadow.models.items()
            },
            sort_keys=True,
        ),
        intervention_observed_count=interventions.observed if interventions else 0,
        allow_count=interventions.recruiterActions.ALLOW if interventions else 0,
        silent_observe_count=(
            interventions.recruiterActions.SILENT_OBSERVE if interventions else 0
        ),
        soft_warn_count=interventions.recruiterActions.SOFT_WARN if interventions else 0,
        hard_block_count=interventions.recruiterActions.HARD_BLOCK if interventions else 0,
        protective_action_counts=json.dumps(
            interventions.protectiveActions if interventions else {}, sort_keys=True
        ),
    )
    db.add(snapshot)
    db.commit()
    return {"success": True, "status_code": 202, "data": {"accepted": True}}
