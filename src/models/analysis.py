from enum import Enum
from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class RiskLevel(str, Enum):
    LOW = 'LOW'
    MEDIUM = 'MEDIUM'
    HIGH = 'HIGH'
    CRITICAL = 'CRITICAL'

class RiskStage(str, Enum):
    SAFE = 'SAFE'
    RECRUITMENT_INITIAL = 'RECRUITMENT_INITIAL'
    GROOMING_APPROACH = 'GROOMING_APPROACH'
    GROOMING_ISOLATION = 'GROOMING_ISOLATION'
    GROOMING_SEXUALIZATION = 'GROOMING_SEXUALIZATION'
    HARASSMENT = 'HARASSMENT'
    MANIPULATION = 'MANIPULATION'

class UXRecommendation(str, Enum):
    NONE = 'NONE'
    SOFT_NUDGE = 'SOFT_NUDGE'
    WARNING_OVERLAY = 'WARNING_OVERLAY'
    SOFT_BLOCK = 'SOFT_BLOCK'
    HARD_BLOCK = 'HARD_BLOCK'

class EmergencyContact(str, Enum):
    POLICE = '088 (Policía Cibernética)'
    EMERGENCY = '911 (Emergencias)'
    SIPINNA = 'SIPINNA (Protección de Menores)'
    CONADIC = 'CONADIC (Línea de la Vida)'
    NONE = 'NONE'

class ActionProtocol(BaseModel):
    ux_recommendation: UXRecommendation
    parent_instruction: str
    emergency_contact: EmergencyContact

class AnalysisData(BaseModel):
    risk_score: int = Field(..., ge=0, le=100)
    risk_level: RiskLevel
    detected_stage: RiskStage
    analysis_summary: str = Field(..., min_length=1)
    dataset_matches: List[str]
    action_protocol: ActionProtocol

class AnalysisMetadata(BaseModel):
    session_id: str
    processed_at: str
    engine_version: Literal['v1.5-flash', 'v1.5-pro', 'claude-3', 'v2.0-flash']

class SentinelAnalysisResponse(BaseModel):
    status: Literal['success', 'error']
    data: AnalysisData
    metadata: AnalysisMetadata
