import re
from typing import Dict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TERM_ID = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$")


class RiskCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    LOW: int = Field(ge=0)
    MEDIUM: int = Field(ge=0)
    HIGH: int = Field(ge=0)
    CRITICAL: int = Field(ge=0)


class ResolutionCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    apiEscalations: int = Field(ge=0)
    local: int = Field(ge=0)
    cachedApiVerdicts: int = Field(ge=0)


class ShadowModelCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    featureSchemaVersion: int | None = Field(default=None, ge=1)
    agreements: int = Field(ge=0)
    disagreements: int = Field(ge=0)


class ShadowCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agreements: int = Field(ge=0)
    disagreements: int = Field(ge=0)
    models: Dict[str, ShadowModelCounts] = Field(default_factory=dict)

    @field_validator("models")
    @classmethod
    def validate_models(cls, value: Dict[str, ShadowModelCounts]):
        if len(value) > 20:
            raise ValueError("shadow.models cannot contain more than 20 model IDs")
        if any(not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", model_id) for model_id in value):
            raise ValueError("shadow model IDs must be short opaque identifiers")
        return value
class RecruiterActionCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ALLOW: int = Field(ge=0)
    SILENT_OBSERVE: int = Field(ge=0)
    SOFT_WARN: int = Field(ge=0)
    HARD_BLOCK: int = Field(ge=0)


PROTECTIVE_ACTIONS = {
    "SHADOW_FLAG",
    "WARN_MINOR",
    "NOTIFY_GUARDIAN",
    "RESTRICT_CONTACT",
    "PRESERVE_EVIDENCE",
    "REPORT_AUTHORITY",
}


class InterventionCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed: int = Field(ge=0)
    recruiterActions: RecruiterActionCounts
    protectiveActions: Dict[str, int] = Field(default_factory=dict)

    @field_validator("protectiveActions")
    @classmethod
    def validate_protective_actions(cls, value: Dict[str, int]) -> Dict[str, int]:
        if any(action not in PROTECTIVE_ACTIONS or count < 0 for action, count in value.items()):
            raise ValueError("protectiveActions contains an invalid action or count")
        return value


class TelemetryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemaVersion: int = Field(default=1, ge=1, le=3)
    totalAnalyses: int = Field(ge=1)
    riskCounts: RiskCounts
    topV3Terms: Dict[str, int] = Field(default_factory=dict)
    resolutions: ResolutionCounts
    shadow: ShadowCounts
    interventions: InterventionCounts | None = None

    @field_validator("topV3Terms")
    @classmethod
    def validate_term_ids(cls, value: Dict[str, int]) -> Dict[str, int]:
        if len(value) > 100:
            raise ValueError("topV3Terms cannot contain more than 100 IDs")
        for term_id, count in value.items():
            if not TERM_ID.fullmatch(term_id) or len(term_id) > 80:
                raise ValueError("topV3Terms keys must be dataset IDs, never free text")
            if count < 0:
                raise ValueError("topV3Terms counts cannot be negative")
        return value

    @model_validator(mode="after")
    def validate_totals(self):
        risk_total = self.riskCounts.LOW + self.riskCounts.MEDIUM + self.riskCounts.HIGH + self.riskCounts.CRITICAL
        resolution_total = (
            self.resolutions.apiEscalations
            + self.resolutions.local
            + self.resolutions.cachedApiVerdicts
        )
        if risk_total != self.totalAnalyses:
            raise ValueError("riskCounts must sum to totalAnalyses")
        if resolution_total != self.totalAnalyses:
            raise ValueError("resolutions must sum to totalAnalyses")
        if self.shadow.agreements + self.shadow.disagreements > self.totalAnalyses:
            raise ValueError("shadow comparisons cannot exceed totalAnalyses")
        if self.shadow.models:
            model_agreements = sum(model.agreements for model in self.shadow.models.values())
            model_disagreements = sum(
                model.disagreements for model in self.shadow.models.values()
            )
            if (
                model_agreements != self.shadow.agreements
                or model_disagreements != self.shadow.disagreements
            ):
                raise ValueError("shadow model counts must equal aggregate shadow counts")
        if self.interventions:
            recruiter_total = sum(self.interventions.recruiterActions.model_dump().values())
            if recruiter_total != self.interventions.observed:
                raise ValueError("recruiterActions must sum to interventions.observed")
            if self.interventions.observed > self.totalAnalyses:
                raise ValueError("interventions.observed cannot exceed totalAnalyses")
        return self
