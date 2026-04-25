from pydantic import BaseModel
from typing import List, Optional

class Message(BaseModel):
    id: str           # Identificador único (UUID)
    user_id: str      # Referencia al usuario
    session_id: str   # Referencia a la sesión
    content: str      # Texto del mensaje
    timestamp: int    # Timestamp (BigInt)

class SDKAnalysis(BaseModel):
    score: int
    risk: str
    escalate: bool
    categories: List[str]
    termsFound: List[str]
    triggeredRules: List[str]
    velocityFlag: bool
    velocityWindow: int

class EscalationRequest(BaseModel):
    # Este es el objeto que el SDK envía cuando requiere análisis de IA
    analysis: SDKAnalysis
    messages: List[Message]

class SyncMessageRequest(BaseModel):
    # Este es para el flujo normal de guardar mensaje y recibir historial
    message: Message
