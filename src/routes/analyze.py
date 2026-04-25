from fastapi import APIRouter
from src.models.conversation import EscalationRequest
from src.controllers.analysis_controller import handle_escalation

router = APIRouter()

@router.post("/analyze")
def analyze(escalation: EscalationRequest):
    """
    Endpoint que recibe la escalación del SDK.
    Contiene el análisis local y el historial de mensajes para la IA.
    """
    return handle_escalation(escalation)
