from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any

from src.database import get_db
from src.core.security import require_admin_key, require_client_key
from src.models.db_models import ApiKey
from src.services.active_learning_service import ActiveLearningService

router = APIRouter()

class EnqueueRequest(BaseModel):
    session_id: str
    primary_verdict: Optional[str] = None
    shadow_probability: Optional[float] = None
    family_id: Optional[str] = None
    features: Optional[List[float]] = None
    random_inclusion_prob: Optional[float] = None
    is_feedback: bool = False

class ReviewSubmissionRequest(BaseModel):
    reviewer_id: str = Field(..., pattern=r"^rev_[A-Za-z0-9_]{3,20}$", description="Seudónimo de revisor rev_XXXX")
    verdict: str = Field(..., description="BENIGN | RISK | INSUFFICIENT_CONTEXT")

class AdjudicationRequest(BaseModel):
    adjudicator_id: str = Field(..., pattern=r"^rev_[A-Za-z0-9_]{3,20}$", description="Seudónimo de adjudicador rev_XXXX")
    final_verdict: str = Field(..., description="BENIGN | RISK | INSUFFICIENT_CONTEXT | REJECTED")
    mark_eligible: bool = True

@router.post("/enqueue")
def enqueue_for_active_learning(
    body: EnqueueRequest,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_client_key),
):
    """Encola un caso en la cola de aprendizaje activo respetando cuotas de familia e idempotencia."""
    result = ActiveLearningService.enqueue_item(
        db=db,
        session_id=body.session_id,
        api_key_hash=api_key.key_hash,
        primary_verdict=body.primary_verdict,
        shadow_probability=body.shadow_probability,
        family_id=body.family_id,
        features=body.features,
        random_inclusion_prob=body.random_inclusion_prob,
        is_feedback=body.is_feedback,
    )
    status_code = 201 if result.get("enqueued") else 200
    return JSONResponse(status_code=status_code, content={"success": True, "data": result})

@router.get("/queue", dependencies=[Depends(require_admin_key)])
def get_active_learning_queue(
    limit: int = Query(20, ge=1, le=100),
    strategy: Optional[str] = Query(None),
    blind: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Obtiene lote para revisión humana. blind=True por defecto para ocultar predicciones."""
    batch = ActiveLearningService.get_review_batch(
        db=db,
        limit=limit,
        strategy_filter=strategy,
        blind=blind,
    )
    return JSONResponse(status_code=200, content={"success": True, "data": {"items": batch, "count": len(batch)}})

@router.post("/review/{item_id}", dependencies=[Depends(require_admin_key)])
def submit_human_review(
    item_id: str,
    body: ReviewSubmissionRequest,
    db: Session = Depends(get_db),
):
    """Registra primera o segunda revisión humana independiente."""
    try:
        result = ActiveLearningService.submit_review(
            db=db,
            item_id=item_id,
            reviewer_id=body.reviewer_id,
            verdict=body.verdict,
        )
        return JSONResponse(status_code=200, content={"success": True, "data": result})
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.post("/adjudicate/{item_id}", dependencies=[Depends(require_admin_key)])
def adjudicate_review(
    item_id: str,
    body: AdjudicationRequest,
    db: Session = Depends(get_db),
):
    """Adjudica caso formalmente. Transiciona a eligible para dataset; nunca dispara entrenamiento automático."""
    try:
        result = ActiveLearningService.adjudicate_item(
            db=db,
            item_id=item_id,
            adjudicator_id=body.adjudicator_id,
            final_verdict=body.final_verdict,
            mark_eligible=body.mark_eligible,
        )
        return JSONResponse(status_code=200, content={"success": True, "data": result})
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.get("/stats", dependencies=[Depends(require_admin_key)])
def get_active_learning_stats(db: Session = Depends(get_db)):
    """Retorna desglose estratificado y estimaciones poblacionales desinsesgadas por IPW."""
    estimates = ActiveLearningService.calculate_debiased_population_estimates(db=db)
    return JSONResponse(status_code=200, content={"success": True, "data": estimates})
