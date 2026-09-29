import os
import sys
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from src.database import get_db, Base
from src.models.db_models import ApiKey, TelemetrySnapshot
from src.services.drift_detection_service import (
    calculate_psi,
    evaluate_telemetry_drift,
    DriftAnalysisResult,
    DriftReport,
)

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(name="db_session")
def db_session_fixture():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(name="client")
def client_fixture(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_psi_insufficient_data():
    base = {"LOW": 10, "MEDIUM": 5}  # total 15 < 30
    target = {"LOW": 12, "MEDIUM": 6}
    result = calculate_psi(base, target, min_sample_threshold=30)
    assert result.status == "INSUFFICIENT_DATA"
    assert result.psi_score == 0.0
    assert "Sample size below threshold" in (result.warning_message or "")


def test_psi_stable_distribution():
    base = {"LOW": 800, "MEDIUM": 150, "HIGH": 40, "CRITICAL": 10}
    target = {"LOW": 790, "MEDIUM": 155, "HIGH": 43, "CRITICAL": 12}
    result = calculate_psi(base, target)
    assert result.status == "STABLE"
    assert result.psi_score < 0.05
    assert result.warning_message is None
    assert len(result.buckets) == 4


def test_psi_traffic_shift():
    # Moderate traffic shift (e.g., more LOW chatter, fewer MEDIUM and HIGH)
    base = {"LOW": 500, "MEDIUM": 300, "HIGH": 150, "CRITICAL": 50}
    target = {"LOW": 680, "MEDIUM": 200, "HIGH": 90, "CRITICAL": 30}
    result = calculate_psi(base, target)
    assert result.status == "TRAFFIC_SHIFT"
    assert 0.10 <= result.psi_score < 0.25
    assert "Likely benign population or topic traffic shift" in (result.warning_message or "")


def test_psi_quality_drift():
    # Severe shift (e.g. HIGH/CRITICAL explosions or mass escalations)
    base = {"LOW": 900, "MEDIUM": 80, "HIGH": 15, "CRITICAL": 5}
    target = {"LOW": 300, "MEDIUM": 200, "HIGH": 350, "CRITICAL": 150}
    result = calculate_psi(base, target)
    assert result.status == "QUALITY_DRIFT"
    assert result.psi_score >= 0.25
    assert "Significant drift detected" in (result.warning_message or "")


def test_evaluate_telemetry_drift_aggregation():
    base_payloads = [
        {
            "riskCounts": {"LOW": 100, "MEDIUM": 10, "HIGH": 5, "CRITICAL": 1},
            "resolutions": {"local": 110, "apiEscalations": 5, "cachedApiVerdicts": 1},
            "shadow": {"agreements": 114, "disagreements": 2},
        },
        {
            "riskCounts": {"LOW": 90, "MEDIUM": 15, "HIGH": 4, "CRITICAL": 2},
            "resolutions": {"local": 105, "apiEscalations": 4, "cachedApiVerdicts": 2},
            "shadow": {"agreements": 108, "disagreements": 3},
        },
    ]

    target_payloads = [
        {
            "riskCounts": {"LOW": 95, "MEDIUM": 12, "HIGH": 5, "CRITICAL": 1},
            "resolutions": {"local": 108, "apiEscalations": 4, "cachedApiVerdicts": 1},
            "shadow": {"agreements": 110, "disagreements": 3},
        },
    ]

    report = evaluate_telemetry_drift("tenant-pilot-01", base_payloads, target_payloads)
    assert isinstance(report, DriftReport)
    assert report.tenant_id == "tenant-pilot-01"
    assert report.risk_drift.status == "STABLE"
    assert "HEALTHY" in report.overall_recommendation


def test_evaluate_telemetry_drift_triggers_active_learning_recommendation():
    base_payloads = [
        {
            "riskCounts": {"LOW": 200, "MEDIUM": 10, "HIGH": 2, "CRITICAL": 0},
            "resolutions": {"local": 210, "apiEscalations": 2, "cachedApiVerdicts": 0},
            "shadow": {"agreements": 210, "disagreements": 2},
        }
    ]
    # Heavy disagreement in shadow model
    target_payloads = [
        {
            "riskCounts": {"LOW": 100, "MEDIUM": 50, "HIGH": 40, "CRITICAL": 20},
            "resolutions": {"local": 120, "apiEscalations": 80, "cachedApiVerdicts": 10},
            "shadow": {"agreements": 100, "disagreements": 110},
        }
    ]

    report = evaluate_telemetry_drift("tenant-drift-test", base_payloads, target_payloads)
    assert report.risk_drift.status == "QUALITY_DRIFT"
    assert "ACTION_REQUIRED: Flagged for active learning batch review" in report.overall_recommendation
    assert "Do not trigger automatic retraining" in report.overall_recommendation


def test_drift_api_endpoint(client, db_session):
    from src.core.security import hash_api_key
    import time

    # Setup tenant API key
    key_str = "sentinel_test_key_drift_123"
    key_hash = hash_api_key(key_str)
    api_key_obj = ApiKey(
        key_hash=key_hash,
        name="Test Pilot",
        scope="client",
        created_at=int(time.time()),
    )
    db_session.add(api_key_obj)

    # Add telemetry snapshots
    for i in range(4):
        db_session.add(
            TelemetrySnapshot(
                id=str(uuid.uuid4()),
                api_key_hash=key_hash,
                created_at=int(time.time()) - (i * 3600),
                purge_at=int(time.time()) + (90 * 86400),
                total_analyses=56,
                low_count=50,
                medium_count=5,
                high_count=1,
                critical_count=0,
                v3_term_counts="{}",
                api_escalations=2,
                local_resolutions=54,
                cached_api_verdicts=0,
                shadow_agreements=55,
                shadow_disagreements=1,
            )
        )
    db_session.commit()

    # Query drift endpoint
    resp = client.get(
        "/api/v1/drift/report",
        headers={"X-API-Key": key_str},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == key_hash[:16]
    assert data["risk_drift"]["status"] == "STABLE"

    # Test unauthorized access to other hash
    unauthorized_resp = client.get(
        "/api/v1/drift/report?target_api_key_hash=evil_hash_999",
        headers={"X-API-Key": key_str},
    )
    assert unauthorized_resp.status_code == 403
