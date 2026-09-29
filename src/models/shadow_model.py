import math
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OPAQUE_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
FEATURE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


class LinearShadowModelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["logistic_regression"]
    modelId: str
    schemaVersion: int = Field(ge=1, le=1000)
    featureNames: list[str] = Field(min_length=1, max_length=512)
    coefficients: list[float] = Field(min_length=1, max_length=512)
    bias: float
    threshold: float = Field(ge=0, le=1)
    trainedRows: int = Field(ge=1)
    trainingNote: str | None = Field(default=None, max_length=500)

    @field_validator("modelId")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        if not OPAQUE_ID.fullmatch(value):
            raise ValueError("modelId must be a short opaque identifier")
        return value

    @field_validator("featureNames")
    @classmethod
    def validate_feature_names(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(
            not FEATURE_NAME.fullmatch(name) for name in value
        ):
            raise ValueError("featureNames must be unique stable identifiers")
        return value

    @field_validator("coefficients")
    @classmethod
    def validate_coefficients(cls, value: list[float]) -> list[float]:
        if any(not math.isfinite(coefficient) for coefficient in value):
            raise ValueError("coefficients must be finite")
        return value

    @field_validator("bias")
    @classmethod
    def validate_bias(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("bias must be finite")
        return value

    @model_validator(mode="after")
    def matching_width(self):
        if len(self.featureNames) != len(self.coefficients):
            raise ValueError("featureNames and coefficients must have equal length")
        return self


class HashedNgramShadowModelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["hashed_ngram_logistic"]
    modelId: str
    schemaVersion: int = Field(ge=1, le=1000)
    structuredFeatureNames: list[str] = Field(default_factory=list, max_length=512)
    hashDimension: int = Field(ge=256, le=65_536)
    minCharNgram: int = Field(ge=2, le=8)
    maxCharNgram: int = Field(ge=2, le=8)
    includeWordUnigrams: bool
    includeWordBigrams: bool
    coefficients: list[float] = Field(min_length=256, max_length=66_048)
    bias: float
    threshold: float = Field(ge=0, le=1)
    trainedRows: int = Field(ge=1)
    trainingNote: str | None = Field(default=None, max_length=500)

    @field_validator("modelId")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        if not OPAQUE_ID.fullmatch(value):
            raise ValueError("modelId must be a short opaque identifier")
        return value

    @field_validator("structuredFeatureNames")
    @classmethod
    def validate_feature_names(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(
            not FEATURE_NAME.fullmatch(name) for name in value
        ):
            raise ValueError("structuredFeatureNames must be unique stable identifiers")
        return value

    @field_validator("coefficients")
    @classmethod
    def validate_coefficients(cls, value: list[float]) -> list[float]:
        if any(not math.isfinite(coefficient) for coefficient in value):
            raise ValueError("coefficients must be finite")
        return value

    @field_validator("bias")
    @classmethod
    def validate_bias(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("bias must be finite")
        return value

    @model_validator(mode="after")
    def validate_contract(self):
        if self.hashDimension & (self.hashDimension - 1):
            raise ValueError("hashDimension must be a power of two")
        if self.minCharNgram > self.maxCharNgram:
            raise ValueError("minCharNgram cannot exceed maxCharNgram")
        expected = self.hashDimension + len(self.structuredFeatureNames)
        if len(self.coefficients) != expected:
            raise ValueError(f"coefficients must contain exactly {expected} values")
        return self


ShadowModelPayload = Annotated[
    LinearShadowModelPayload | HashedNgramShadowModelPayload,
    Field(discriminator="kind"),
]
