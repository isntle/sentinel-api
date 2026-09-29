from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, ConfigDict

PolicyMode = Literal["shadow", "review", "enforce"]
DecisionRiskBand = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"]
DecisionDisposition = Literal["ALLOW", "REVIEW", "INTERVENE", "ABSTAIN"]
SignalState = Literal["present", "absent", "unknown"]
UncertaintyStatus = Literal[
    "calibrated",
    "uncalibrated",
    "insufficient_context",
    "timeout",
    "provider_error",
]
ConfidenceLevel = Literal["low", "medium", "high", "unknown"]


class DecisionSignal(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: str = Field(..., min_length=1)
    state: SignalState = "unknown"
    score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: List[Union[int, str]] = Field(default_factory=list, alias="evidenceRefs")


class DecisionUncertainty(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: UncertaintyStatus = "uncalibrated"
    calibrated_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, alias="calibratedScore")
    confidence: ConfidenceLevel = "unknown"
    reason: Optional[str] = None


class DecisionVersions(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    engine: str = Field(..., min_length=1)
    policy: str = Field(..., min_length=1)
    region_pack: Optional[str] = Field(default=None, alias="regionPack")
    model: Optional[str] = None


class DecisionRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    policy_mode: PolicyMode = Field(default="shadow", alias="policyMode")
    case_ref: str = Field(..., min_length=1, alias="caseRef")
    risk_band: DecisionRiskBand = Field(..., alias="riskBand")
    disposition: DecisionDisposition = "REVIEW"
    signals: List[DecisionSignal] = Field(default_factory=list)
    uncertainty: DecisionUncertainty
    versions: DecisionVersions
    created_at: Optional[int] = Field(default=None, alias="createdAt")
