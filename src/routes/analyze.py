from fastapi import APIRouter
from fastapi.responses import JSONResponse
from src.models.conversation import EscalationRequest
from src.controllers.analysis_controller import handle_escalation

router = APIRouter()

@router.post("/analyze")
def analyze(escalation: EscalationRequest):
    result = handle_escalation(escalation)
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "status_code": 200,
            "data": {
                "score": result.get("score"),
                "risk": result.get("risk"),
                "stage": result.get("stage"),
                "categories": result.get("categories"),
                "termsFound": result.get("termsFound"),
                "ux_recommendation": result.get("ux_recommendation"),
            },
        },
    )
