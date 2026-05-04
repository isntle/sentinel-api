from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from src.database import get_db
from src.models.hot_terms import SuggestTermRequest, ClassifyTermRequest
from src.services.hot_terms_service import (
    get_approved_terms,
    suggest_term,
    classify_and_approve_term,
)

router = APIRouter()

@router.get("")
def get_hot_terms(db: Session = Depends(get_db)):
    """
    Devuelve todos los términos aprobados.
    El SDK llama este endpoint al inicializar para extender su dataset local.
    """
    terms = get_approved_terms(db)
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": [
            {
                "id": t.id,
                "term": t.term,
                "category": t.category,
                "weight": t.weight,
                "variants": t.variants.split(",") if t.variants else [],
                "created_at": t.created_at,
            }
            for t in terms
        ],
    })

@router.post("/suggest")
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

@router.post("/classify")
def classify_term(body: ClassifyTermRequest, db: Session = Depends(get_db)):
    """
    Usa Groq (LLaMA 3.3 70B) para evaluar si el término es jerga de riesgo real.
    Si lo es, lo aprueba automáticamente y queda disponible para el SDK.
    """
    result = classify_and_approve_term(db, body.term, body.source)
    status = 200 if result["approved"] else 200
    return JSONResponse(status_code=status, content={
        "success": True,
        "status_code": status,
        "data": result,
    })
