from enum import Enum
from pydantic import BaseModel, Field


class Stage(str, Enum):
    NINGUNA = 'NINGUNA'
    CAPTACION = 'CAPTACION'
    INDUCCION_COOPTACION = 'INDUCCION/COOPTACION'
    INCUBACION = 'INCUBACION'
    UTILIZACION_INSTRUMENTALIZACION = 'UTILIZACION/INSTRUMENTALIZACION'


class UXRecommendation(str, Enum):
    NONE = 'NONE'
    SOFT_NUDGE = 'SOFT_NUDGE'
    WARNING_OVERLAY = 'WARNING_OVERLAY'
    SOFT_BLOCK = 'SOFT_BLOCK'
    HARD_BLOCK = 'HARD_BLOCK'


class Tier2Result(BaseModel):
    ux_recommendation: UXRecommendation
    stage: Stage
    confidence: float = Field(..., ge=0.0, le=1.0)
    summary: str = Field(..., min_length=1)
    false_positive: bool
