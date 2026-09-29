from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from src.database import get_db
from src.models.hot_terms import SuggestTermRequest, ClassifyTermRequest
from src.services.hot_terms_service import (
    get_approved_terms,
    suggest_term,
    classify_and_approve_term,
    publish_version,
    rollback_to_version
)
from src.core.security import require_client_key, require_admin_key
from src.models.db_models import DatasetVersion
from src.services.base_pack_service import load_base_pack
from src.services.artifact_signing import build_signed_artifact

router = APIRouter()

@router.get("", dependencies=[Depends(require_client_key)])
def get_hot_terms(
    pack: Literal["dynamic", "full"] = Query(default="dynamic"),
    db: Session = Depends(get_db),
):
    """
    Devuelve todos los términos aprobados.
    El SDK llama este endpoint al inicializar para extender su dataset local.
    """
    terms = get_approved_terms(db)
    base_pack = load_base_pack() if pack == "full" else None
    latest_version = db.query(DatasetVersion).order_by(DatasetVersion.version.desc()).first()
    dataset_version = latest_version.version if latest_version else None
    base_pack_version = base_pack["version"] if base_pack else None
    response_terms = (base_pack["terms"] if base_pack else []) + [
        {
            "id": t.id,
            "term": t.term,
            "category": t.category,
            "weight": t.weight,
            "variants": t.variants.split(",") if t.variants else [],
            "created_at": t.created_at,
        }
        for t in terms
    ]
    artifact = None
    if pack == "full":
        artifact = build_signed_artifact(
            kind="region_pack",
            artifact_id="MX",
            version=f"{base_pack_version}+dynamic.{dataset_version or 0}",
            payload={
                "basePackVersion": base_pack_version,
                "datasetVersion": dataset_version,
                "terms": response_terms,
            },
        )
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "dataset_version": dataset_version,
        "base_pack_version": base_pack_version,
        "data": response_terms,
        "artifact": artifact,
    })

@router.post("/suggest", dependencies=[Depends(require_admin_key)])
def suggest_new_term(body: SuggestTermRequest, db: Session = Depends(get_db)):
    """
    Agrega un término candidato sin aprobarlo.
    Para revisión manual o posterior clasificación con IA.
    """
    term = suggest_term(db, body.term, body.source)
    return JSONResponse(status_code=201, content={
        "success": True,
        "status_code": 201,
        "data": {
            "id": term.id,
            "term": term.term,
            "approved": term.approved,
            "message": "Término recibido. Pendiente de clasificación.",
        },
    })

@router.post("/classify", dependencies=[Depends(require_admin_key)])
def classify_term(body: ClassifyTermRequest, db: Session = Depends(get_db)):
    """
    Usa Groq (LLaMA 3.3 70B) para evaluar si el término es jerga de riesgo real.
    Si lo es, lo deja staged para revisión humana; aún no llega al SDK.
    """
    result = classify_and_approve_term(db, body.term, body.source)
    status = 200
    return JSONResponse(status_code=status, content={
        "success": True,
        "status_code": status,
        "data": result,
    })

@router.get("/rejected", dependencies=[Depends(require_admin_key)])
def get_rejected_terms(db: Session = Depends(get_db)):
    """
    Devuelve la memoria de términos que Groq rechazó (para evitar reclasificarlos).
    Para auditoría y revisión humana.
    """
    from src.models.db_models import RejectedTerm
    terms = db.query(RejectedTerm).order_by(RejectedTerm.rejected_at.desc()).all()
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": [
            {
                "id": t.id,
                "term": t.term,
                "source": t.source,
                "reasoning": t.reasoning,
                "rejected_at": t.rejected_at,
            }
            for t in terms
        ],
    })

@router.get("/pipeline-stats", dependencies=[Depends(require_admin_key)])
def get_pipeline_statistics(db: Session = Depends(get_db)):
    """
    Devuelve métricas del embudo del scraper (Fase 2.3).
    """
    from src.services.candidate_scorer import get_pipeline_stats
    stats = get_pipeline_stats(db)
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": stats
    })

@router.post("/publish", dependencies=[Depends(require_admin_key)])
def publish_staged_terms(db: Session = Depends(get_db)):
    """
    Publica solo los términos staged marcados como revisados y crea una versión.
    """
    version = publish_version(db)
    if not version:
        return JSONResponse(status_code=400, content={
            "success": False,
            "status_code": 400,
            "message": "No hay términos pendientes de publicar."
        })
        
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": {
            "version": version.version,
            "created_at": version.created_at,
            "description": version.description
        }
    })

@router.post("/rollback/{version_id}", dependencies=[Depends(require_admin_key)])
def rollback_dataset(version_id: int, db: Session = Depends(get_db)):
    """
    Restaura el dataset a una versión previa y descarta los aprobados actuales.
    """
    success = rollback_to_version(db, version_id)
    if not success:
        return JSONResponse(status_code=404, content={
            "success": False,
            "status_code": 404,
            "message": f"Versión {version_id} no encontrada."
        })
        
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "message": f"Dataset restaurado exitosamente a la versión {version_id}."
    })
