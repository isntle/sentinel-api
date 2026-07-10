from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from src.database import get_db
from src.models.conversation import EscalationRequest
from src.controllers.analysis_controller import handle_escalation

router = APIRouter()

@router.post("/analyze")
def analyze(escalation: EscalationRequest, db: Session = Depends(get_db)):
    result = handle_escalation(escalation, db=db)
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "status_code": 200,
            "data": {
                "ux_recommendation": result.get("ux_recommendation"),
                "stage": result.get("stage"),
                "confidence": result.get("confidence"),
                "summary": result.get("summary"),
                "false_positive": result.get("false_positive"),
                # Riesgo de red del actor (reclutamiento organizado cross-sesión)
                "network": result.get("network"),
                # Plan de intervención graduada (qué ve el reclutador vs. qué
                # protege a la víctima). La plataforma lo aplica o ajusta.
                "intervention": result.get("intervention"),
            },
        },
    )
