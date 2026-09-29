import pytest
from pydantic import ValidationError
from src.models.decision import DecisionRecord, DecisionSignal, DecisionUncertainty, DecisionVersions


def test_valid_decision_record_shadow_mode():
    data = {
        "schemaVersion": 1,
        "policyMode": "shadow",
        "caseRef": "case-mx-001",
        "riskBand": "MEDIUM",
        "disposition": "REVIEW",
        "signals": [
            {
                "kind": "surveillance_task",
                "state": "present",
                "score": 0.85,
                "evidenceRefs": [1, 3],
            }
        ],
        "uncertainty": {
            "status": "calibrated",
            "calibratedScore": 0.78,
            "confidence": "high",
            "reason": "corroborated_with_actor_layer",
        },
        "versions": {
            "engine": "1.0.3",
            "policy": "v1.0",
            "regionPack": "mx-v1",
            "model": "shadow-model-hashed-v1",
        },
        "createdAt": 1727500000000,
    }

    record = DecisionRecord.model_validate(data)
    assert record.schema_version == 1
    assert record.policy_mode == "shadow"
    assert record.case_ref == "case-mx-001"
    assert record.risk_band == "MEDIUM"
    assert record.disposition == "REVIEW"
    assert len(record.signals) == 1
    assert record.signals[0].kind == "surveillance_task"
    assert record.signals[0].evidence_refs == [1, 3]
    assert record.uncertainty.status == "calibrated"
    assert record.uncertainty.calibrated_score == 0.78


def test_abstain_insufficient_context_record():
    data = {
        "schemaVersion": 1,
        "policyMode": "shadow",
        "caseRef": "case-ambiguous-002",
        "riskBand": "UNKNOWN",
        "disposition": "ABSTAIN",
        "signals": [],
        "uncertainty": {
            "status": "insufficient_context",
            "calibratedScore": None,
            "confidence": "unknown",
            "reason": "truncated_dialogue_no_intent",
        },
        "versions": {
            "engine": "1.0.3",
            "policy": "v1.0",
        },
    }
    record = DecisionRecord.model_validate(data)
    assert record.risk_band == "UNKNOWN"
    assert record.disposition == "ABSTAIN"
    assert record.uncertainty.status == "insufficient_context"
    assert record.uncertainty.calibrated_score is None


def test_invalid_policy_mode():
    data = {
        "schemaVersion": 1,
        "policyMode": "invalid_mode_action",
        "caseRef": "c1",
        "riskBand": "LOW",
        "disposition": "ALLOW",
        "signals": [],
        "uncertainty": {"status": "uncalibrated"},
        "versions": {"engine": "1.0.3", "policy": "v1.0"},
    }
    with pytest.raises(ValidationError):
        DecisionRecord.model_validate(data)


def test_score_out_of_range():
    data = {
        "schemaVersion": 1,
        "policyMode": "shadow",
        "caseRef": "c1",
        "riskBand": "LOW",
        "disposition": "ALLOW",
        "signals": [{"kind": "k1", "score": 1.5}],  # Invalid > 1.0
        "uncertainty": {"status": "uncalibrated"},
        "versions": {"engine": "1.0.3", "policy": "v1.0"},
    }
    with pytest.raises(ValidationError):
        DecisionRecord.model_validate(data)
