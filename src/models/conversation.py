from pydantic import BaseModel, Field, field_validator
from typing import Dict, List, Literal, Optional

class Message(BaseModel):
    id: str = Field(..., min_length=1, description="UUID del mensaje")
    user_id: str = Field(..., min_length=1, description="UUID del usuario")
    session_id: str = Field(..., min_length=1, description="UUID de la sesión")
    content: str = Field(..., min_length=1, max_length=5000, description="Texto del mensaje")
    timestamp: int = Field(..., gt=0, description="Unix timestamp en segundos")
    source: Optional[Literal["text", "voice_transcript"]] = None

    @field_validator("id", "user_id", "session_id")
    @classmethod
    def no_whitespace_only(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("El campo no puede ser solo espacios en blanco")
        return v


class NormalizerLayer(BaseModel):
    score: int = Field(..., ge=0, le=100)
    features: List[str] = Field(default_factory=list)
    triggeredRules: List[str] = Field(default_factory=list)
    transformations: List[str] = Field(default_factory=list)


class V3Layer(BaseModel):
    score: int = Field(..., ge=0, le=100)
    originalScore: Optional[int] = Field(default=None, ge=0, le=100)
    dampenersApplied: List[str] = Field(default_factory=list)
    terms: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    triggeredRules: List[str] = Field(default_factory=list)


class V4Layer(BaseModel):
    score: int = Field(..., ge=0, le=100)
    features: List[str] = Field(default_factory=list)
    triggeredRules: List[str] = Field(default_factory=list)
    explicitSignals: List[str] = Field(default_factory=list)


class StageFirstSeen(BaseModel):
    stage: str
    firstSeenAt: int


class TemporalLayer(BaseModel):
    """Progresión temporal detectada por el SDK (captación lenta multi-día)."""
    stagesPresent: List[str] = Field(default_factory=list)
    orderedProgression: bool = False
    spanDays: float = 0
    triggeredRules: List[str] = Field(default_factory=list)
    timeline: List[StageFirstSeen] = Field(default_factory=list)


class ActorLayer(BaseModel):
    """Asimetría de emisor detectada por el SDK: quién concentra las tácticas."""
    analyzed: bool = False
    profiles: List["ActorProfile"] = Field(default_factory=list)
    aggressorSender: Optional[str] = None
    concentration: float = 0
    triggeredRules: List[str] = Field(default_factory=list)


class ActorProfile(BaseModel):
    sender: str
    categories: List[str] = Field(default_factory=list)
    directedActionCount: int = Field(default=0, ge=0)
    score: int = Field(default=0, ge=0)


class Layers(BaseModel):
    normalizer: NormalizerLayer
    v3: V3Layer
    v4: V4Layer
    # Opcionales para compatibilidad con SDKs anteriores que no las envían
    temporal: Optional[TemporalLayer] = None
    actor: Optional[ActorLayer] = None


class EscalationRequest(BaseModel):
    score: int = Field(..., ge=0, le=100, description="Score agregado del SDK (0-100)")
    risk: str = Field(..., min_length=1)
    escalate: bool
    layers: Layers
    velocityFlag: bool
    velocityWindow: int = Field(..., ge=0)
    messagesAnalyzed: int = Field(..., ge=0)
    uniqueCategories: List[str] = Field(default_factory=list)
    # Banda de edad del usuario protegido (opcional; el SDK la envía si la tiene).
    ageBand: Optional[str] = None
    escalationReason: Optional[Literal[
        "none_low_risk", "confident_local_proof", "uncertain_needs_llm"
    ]] = None
    # Versiones que el SDK declara haber usado. No se infieren: para evidencia
    # legal es preferible `None` a afirmar una versión incorrecta.
    datasetVersions: Optional["DatasetVersions"] = None
    messages: List[Message] = Field(..., min_length=1, description="Debe tener al menos un mensaje")


class DatasetVersions(BaseModel):
    regionPacks: Dict[str, str] = Field(default_factory=dict)
    apiHotTerms: Optional[int] = None

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
