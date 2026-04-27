from fastapi import APIRouter
from fastapi.responses import JSONResponse
from src.models.conversation import EscalationRequest
from src.controllers.analysis_controller import handle_escalation

router = APIRouter()

@router.post("/analyze")
def analyze(escalation: EscalationRequest):
    result = handle_escalation(escalation)
    data = {
        "ux_recommendation": result.get("ux_recommendation"),
        "stage": result.get("stage"),
        "confidence": result.get("confidence"),
        "summary": result.get("summary"),
        "false_positive": result.get("false_positive"),
    }
    if result.get("fallback"):
        data["fallback"] = True
        data["fallback_reason"] = result.get("fallback_reason")
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "status_code": 200,
            "data": data,
        },
    )
