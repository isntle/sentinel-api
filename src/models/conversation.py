from pydantic import BaseModel, Field, field_validator
from typing import List
import uuid

class Message(BaseModel):
    id: str = Field(..., min_length=1, description="UUID del mensaje")
    user_id: str = Field(..., min_length=1, description="UUID del usuario")
    session_id: str = Field(..., min_length=1, description="UUID de la sesión")
    content: str = Field(..., min_length=1, max_length=5000, description="Texto del mensaje")
    timestamp: int = Field(..., gt=0, description="Unix timestamp en segundos")

    @field_validator("id", "user_id", "session_id")
    @classmethod
    def no_whitespace_only(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("El campo no puede ser solo espacios en blanco")
        return v

class SDKAnalysis(BaseModel):
    score: int = Field(..., ge=0, le=100, description="Score de riesgo local (0-100)")
    risk: str = Field(..., min_length=1)
    escalate: bool
    categories: List[str] = Field(..., min_length=0)
    termsFound: List[str] = Field(..., min_length=0)
    triggeredRules: List[str] = Field(..., min_length=0)
    velocityFlag: bool
    velocityWindow: int = Field(..., ge=0) or None  

class EscalationRequest(BaseModel):
    analysis: SDKAnalysis
    messages: List[Message] = Field(..., min_length=1, description="Debe tener al menos un mensaje")

class IncomingMessage(BaseModel):
    user_id: str = Field(..., min_length=1, description="UUID del usuario")
    session_id: str = Field(..., min_length=1, description="UUID de la sesión")
    content: str = Field(..., min_length=1, max_length=5000, description="Texto del mensaje")
    timestamp: int = Field(..., gt=0, description="Unix timestamp en segundos")

    @field_validator("user_id", "session_id")
    @classmethod
    def no_whitespace_only(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("El campo no puede ser solo espacios en blanco")
        return v

class SyncMessageRequest(BaseModel):
    message: IncomingMessage
