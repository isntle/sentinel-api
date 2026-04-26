from src.models.conversation import EscalationRequest
from src.services.analysis_service import analyze_conversation

def handle_escalation(escalation: EscalationRequest):
    """
    Recibe la escalación del SDK (análisis local + mensajes)
    y delega el análisis profundo a la IA.
    """
    # Aquí ya no evaluamos el score, confiamos en la decisión de escalado del SDK.
    # Enviamos todo el paquete al servicio de Gemini.
    result = analyze_conversation(escalation)
    
    return result
