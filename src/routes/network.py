from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy.orm import Session
from src.database import get_db
from src.core.security import require_admin_key, require_client_key
from src.services.network_service import (
    top_risky_actors, purge_expired_sightings, record_and_score,
)

router = APIRouter()


class NetworkReportRequest(BaseModel):
    aggressor_user_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    aggressor_texts: List[str] = Field(default_factory=list)
    risk: Optional[str] = None
    categories: List[str] = Field(default_factory=list)


@router.post("/report", dependencies=[Depends(require_client_key)])
def report_actor(body: NetworkReportRequest, db: Session = Depends(get_db)):
    """
    Registro BARATO de un avistamiento de actor, SIN invocar el LLM. Lo llama el
    SDK cuando resolvió el veredicto localmente pero identificó un agresor, para
    preservar la detección de reclutamiento organizado cross-sesión sin costo de
    capa cognitiva. Devuelve el riesgo de red agregado.
    """
    network = record_and_score(
        db=db,
        aggressor_user_id=body.aggressor_user_id,
        session_id=body.session_id,
        aggressor_texts=body.aggressor_texts,
        risk=body.risk or "",
        categories=body.categories,
    )
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": network,
    })

@router.get("/actors", dependencies=[Depends(require_admin_key)])
def list_risky_actors(db: Session = Depends(get_db)):
    """
    Vista administrativa: actores con presencia en múltiples sesiones (posible
    reclutamiento organizado). Solo agregados hasheados, sin identidad en claro.
    """
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": top_risky_actors(db),
    })

@router.post("/purge", dependencies=[Depends(require_admin_key)])
def purge_sightings(db: Session = Depends(get_db)):
    """Fuerza la purga de avistamientos vencidos (retención)."""
    deleted = purge_expired_sightings(db)
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": {"purged": deleted},
    })
