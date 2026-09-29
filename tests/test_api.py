import pytest
import base64
import time
import hashlib
import json
import uuid
import sys
import os
from types import SimpleNamespace
from unittest.mock import patch
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from main import app
from src.database import get_db, Base
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from src.models.db_models import (
    AnalysisRecord,
    ApiKey,
    CandidateSighting,
    DatasetVersion,
    EvidencePackage,
    Feedback,
    HotTerm,
    RejectedTerm,
    ScraperRun,
    ShadowModelArtifact,
    ShadowModelRelease,
    TelemetrySnapshot,
)
from src.core.security import hash_api_key, require_admin_key
from src.core.cors import configure_cors
from src.models.conversation import (
    ActorLayer,
    EscalationRequest,
    Layers,
    Message,
    NormalizerLayer,
    V3Layer,
    V4Layer,
)
from src.routes.scraper import purge_expired
from src.services.evidence_service import canonical_json, record_eligible_analysis
from src.services.telemetry_token import issue_telemetry_token, verify_telemetry_token
from src.services.calibration_service import (
    apply_calibration_proposal,
    generate_calibration_proposal,
)
from src.services.candidate_scorer import (
    get_mature_candidates,
    get_pipeline_stats,
    is_hard_filtered,
)
from src.services.hot_terms_service import classify_terms_batch
from src.services.scraper_service import run_scraper
from src.services.monthly_value_service import (
    build_monthly_value_report,
    render_monthly_value_html,
)
from src.routes.admin import router as admin_router
from src.routes.hot_terms import router as hot_terms_router
from src.config import settings

@pytest.fixture(scope="session")
def db_session():
    """Una sola DB efímera por corrida; jamás toca sentinel.db ni producción."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    TestingSession = sessionmaker(bind=test_engine)
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()

@pytest.fixture(scope="session")
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def isolated_db():
    isolated_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=isolated_engine)
    TestingSession = sessionmaker(bind=isolated_engine)
    with TestingSession() as db:
        yield db

@pytest.fixture
def client_key(db_session: Session):
    key = "test_client_key"
    key_hash = hash_api_key(key)
    
    existing = db_session.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if not existing:
        ak = ApiKey(key_hash=key_hash, name="Test Client", scope="client", created_at=int(time.time()))
        db_session.add(ak)
        db_session.commit()
        
    return key

@pytest.fixture
def admin_key(db_session: Session):
    key = "test_admin_key"
    key_hash = hash_api_key(key)
    
    existing = db_session.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if not existing:
        ak = ApiKey(key_hash=key_hash, name="Test Admin", scope="admin", created_at=int(time.time()))
        db_session.add(ak)
        db_session.commit()
        
    return key


def test_no_api_key_rejected(client):
    response = client.get("/api/v1/hot-terms")
    assert response.status_code == 401
    assert "missing" in response.json()["detail"].lower()

def test_client_key_accepted_on_client_route(client, client_key):
    response = client.get("/api/v1/hot-terms", headers={"X-API-Key": client_key})
    assert response.status_code == 200

def test_client_key_rejected_on_admin_route(client, client_key):
    # /api/v1/admin/scrape requires admin key
    response = client.post("/api/v1/admin/scrape", headers={"X-API-Key": client_key})
    assert response.status_code == 403
    assert "Not enough permissions" in response.json()["detail"]

def test_admin_key_accepted_on_admin_route(client, admin_key):
    # using get /api/v1/hot-terms/pipeline-stats which is admin
    response = client.get("/api/v1/hot-terms/pipeline-stats", headers={"X-API-Key": admin_key})
    assert response.status_code == 200


def test_admin_dashboard_requires_admin_key(client):
    response = client.get("/admin/review")
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")


def test_admin_dashboard_rejects_api_key_in_query_string(client, admin_key):
    response = client.get(f"/admin/review?api_key={admin_key}")
    assert response.status_code == 401


def test_admin_dashboard_accepts_basic_auth_without_query_secret(client, admin_key):
    credentials = base64.b64encode(f"sentinel:{admin_key}".encode()).decode()
    response = client.get(
        "/admin/review",
        headers={"Authorization": f"Basic {credentials}"},
    )
    assert response.status_code == 200
    assert "api_key=" not in response.text

def test_admin_key_accepted_on_client_route(client, admin_key):
    # Admin should also be able to access client routes if they use the client dependency,
    # because admin scope check in RequireKey is only for required_scope="admin".
    # Wait, our RequireKey logic currently only checks: 
    # if required == admin and scope != admin -> 403. 
    # This means admin CAN access client endpoints because required == client, and it doesn't fail.
    response = client.get("/api/v1/hot-terms", headers={"X-API-Key": admin_key})
    assert response.status_code == 200


def test_authenticated_full_pack_excludes_public_seed_and_includes_complement(
    client, client_key, monkeypatch
):
    private_key = Ed25519PrivateKey.generate()
    private_raw = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    monkeypatch.setattr(
        settings,
        "ARTIFACT_SIGNING_PRIVATE_KEY",
        base64.urlsafe_b64encode(private_raw).rstrip(b"=").decode(),
    )
    monkeypatch.setattr(settings, "ARTIFACT_SIGNING_KEY_ID", "test-artifact-key")
    response = client.get(
        "/api/v1/hot-terms",
        params={"pack": "full"},
        headers={"X-API-Key": client_key},
    )
    assert response.status_code == 200
    body = response.json()
    ids = {term["id"] for term in body["data"]}
    assert body["base_pack_version"] == "3.0.0"
    assert "REC-023" in ids
    assert "REC-001" not in ids
    assert len([term for term in body["data"] if term["id"] == "REC-023"]) == 1
    artifact = body["artifact"]
    assert artifact["keyId"] == "test-artifact-key"
    payload_bytes = base64.urlsafe_b64decode(
        artifact["payload"] + "=" * (-len(artifact["payload"]) % 4)
    )
    signature = base64.urlsafe_b64decode(
        artifact["signature"] + "=" * (-len(artifact["signature"]) % 4)
    )
    private_key.public_key().verify(signature, payload_bytes)
    signed_body = json.loads(payload_bytes)
    assert signed_body["kind"] == "region_pack"
    assert signed_body["artifactId"] == "MX"
    assert signed_body["payload"]["terms"] == body["data"]

    with pytest.raises(InvalidSignature):
        private_key.public_key().verify(signature, payload_bytes + b"tampered")


def _shadow_model_payload(model_id: str):
    return {
        "kind": "logistic_regression",
        "modelId": model_id,
        "schemaVersion": 2,
        "featureNames": ["score_total", "intent_signal_density"],
        "coefficients": [0.5, 1.25],
        "bias": -0.4,
        "threshold": 0.5,
        "trainedRows": 185,
        "trainingNote": "test artifact",
    }


def _hashed_shadow_model_payload(model_id: str):
    return {
        "kind": "hashed_ngram_logistic",
        "modelId": model_id,
        "schemaVersion": 2,
        "structuredFeatureNames": [],
        "hashDimension": 256,
        "minCharNgram": 3,
        "maxCharNgram": 5,
        "includeWordUnigrams": True,
        "includeWordBigrams": True,
        "coefficients": [0.0] * 256,
        "bias": -0.4,
        "threshold": 0.5,
        "trainedRows": 185,
        "trainingNote": "hashed test artifact",
    }


def test_shadow_model_registry_validates_hashed_contract(client, admin_key, db_session):
    model_id = f"test-hashed-{uuid.uuid4().hex[:8]}"
    try:
        valid = client.post(
            "/api/v1/models/shadow/stage",
            json=_hashed_shadow_model_payload(model_id),
            headers={"X-API-Key": admin_key},
        )
        assert valid.status_code == 201

        wrong_width = _hashed_shadow_model_payload(f"{model_id}-bad")
        wrong_width["coefficients"] = wrong_width["coefficients"][:-1]
        invalid = client.post(
            "/api/v1/models/shadow/stage",
            json=wrong_width,
            headers={"X-API-Key": admin_key},
        )
        assert invalid.status_code == 422
    finally:
        db_session.query(ShadowModelArtifact).filter(
            ShadowModelArtifact.model_id.like(f"{model_id}%")
        ).delete(synchronize_session=False)
        db_session.commit()


def test_shadow_model_registry_publish_and_monotonic_rollback(
    client, client_key, admin_key, db_session, monkeypatch
):
    private_key = Ed25519PrivateKey.generate()
    private_raw = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    monkeypatch.setattr(
        settings,
        "ARTIFACT_SIGNING_PRIVATE_KEY",
        base64.urlsafe_b64encode(private_raw).rstrip(b"=").decode(),
    )
    monkeypatch.setattr(settings, "ARTIFACT_SIGNING_KEY_ID", "model-registry-test")
    first_id = f"test-model-a-{uuid.uuid4().hex[:8]}"
    second_id = f"test-model-b-{uuid.uuid4().hex[:8]}"
    try:
        assert client.post(
            "/api/v1/models/shadow/stage", json=_shadow_model_payload(first_id)
        ).status_code == 401
        for model_id in (first_id, second_id):
            response = client.post(
                "/api/v1/models/shadow/stage",
                json=_shadow_model_payload(model_id),
                headers={"X-API-Key": admin_key},
            )
            assert response.status_code == 201

        release_a = client.post(
            f"/api/v1/models/shadow/publish/{first_id}",
            headers={"X-API-Key": admin_key},
        ).json()["data"]["release_version"]
        release_b = client.post(
            f"/api/v1/models/shadow/publish/{second_id}",
            headers={"X-API-Key": admin_key},
        ).json()["data"]["release_version"]
        rollback_a = client.post(
            f"/api/v1/models/shadow/rollback/{first_id}",
            headers={"X-API-Key": admin_key},
        ).json()["data"]["release_version"]
        assert release_a < release_b < rollback_a

        current = client.get(
            "/api/v1/models/shadow/current",
            headers={"X-API-Key": client_key},
        )
        assert current.status_code == 200
        body = current.json()
        assert body["data"]["releaseVersion"] == rollback_a
        assert body["data"]["model"]["modelId"] == first_id
        assert body["artifact"]["keyId"] == "model-registry-test"
    finally:
        db_session.query(ShadowModelRelease).filter(
            ShadowModelRelease.model_id.in_([first_id, second_id])
        ).delete(synchronize_session=False)
        db_session.query(ShadowModelArtifact).filter(
            ShadowModelArtifact.model_id.in_([first_id, second_id])
        ).delete(synchronize_session=False)
        db_session.commit()


def _critical_escalation(session_id: str) -> EscalationRequest:
    return EscalationRequest(
        score=80,
        risk="CRITICAL",
        escalate=True,
        layers=Layers(
            normalizer=NormalizerLayer(score=2, features=["N0-F001"]),
            v3=V3Layer(
                score=40,
                originalScore=45,
                dampenersApplied=["school"],
                terms=["REC-001"],
                categories=["reclutamiento"],
                triggeredRules=["MCR-001"],
            ),
            v4=V4Layer(score=38, explicitSignals=["EX-002"]),
            actor=ActorLayer(analyzed=True, aggressorSender="actor-1"),
        ),
        velocityFlag=False,
        velocityWindow=0,
        messagesAnalyzed=2,
        uniqueCategories=["reclutamiento"],
        escalationReason="uncertain_needs_llm",
        messages=[
            Message(
                id="m-2",
                user_id="actor-1",
                session_id=session_id,
                content="manda tu ubicación",
                timestamp=1750000002,
                source="text",
            ),
            Message(
                id="m-1",
                user_id="actor-1",
                session_id=session_id,
                content="hay jale",
                timestamp=1750000001,
                source="text",
            ),
        ],
    )


def _record_for_evidence(db_session: Session, client_key: str, session_id: str):
    verdict = {
        "ux_recommendation": "HARD_BLOCK",
        "stage": "UTILIZACION/INSTRUMENTALIZACION",
        "confidence": 0.98,
        "summary": "Busca ayuda de una persona de confianza.",
        "false_positive": False,
    }
    return record_eligible_analysis(
        db_session,
        _critical_escalation(session_id),
        verdict,
        hash_api_key(client_key),
    )


def test_evidence_endpoint_requires_authentication(client):
    response = client.post("/api/v1/evidence/session-without-key")
    assert response.status_code == 401


def test_evidence_hash_is_deterministic_and_reproducible(client, client_key, db_session):
    session_id = f"evidence-deterministic-{uuid.uuid4()}"
    _record_for_evidence(db_session, client_key, session_id)

    first = client.post(
        f"/api/v1/evidence/{session_id}",
        headers={"X-API-Key": client_key},
    )
    second = client.post(
        f"/api/v1/evidence/{session_id}",
        headers={"X-API-Key": client_key},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    package = first.json()
    canonical = canonical_json(package["payload"]).encode("utf-8")
    calculated_once = hashlib.sha256(canonical).hexdigest()
    calculated_twice = hashlib.sha256(canonical).hexdigest()
    assert calculated_once == calculated_twice == package["integrity"]["content_hash"]
    assert [message["id"] for message in package["payload"]["messages"]] == ["m-1", "m-2"]


def test_generated_evidence_is_exempt_from_normal_retention(client, client_key, db_session):
    session_id = f"evidence-retention-{uuid.uuid4()}"
    record = _record_for_evidence(db_session, client_key, session_id)
    response = client.post(
        f"/api/v1/evidence/{session_id}",
        headers={"X-API-Key": client_key},
    )
    assert response.status_code == 200

    record_id = record.id
    record.purge_at = int(time.time()) - 1
    db_session.commit()
    purge_expired(db_session)

    assert db_session.query(AnalysisRecord).filter(AnalysisRecord.id == record_id).first() is None
    package = (
        db_session.query(EvidencePackage)
        .filter(EvidencePackage.analysis_record_id == record_id)
        .first()
    )
    assert package is not None
    assert hashlib.sha256(package.canonical_payload.encode("utf-8")).hexdigest() == package.content_hash


def _telemetry_payload():
    return {
        "schemaVersion": 1,
        "totalAnalyses": 7,
        "riskCounts": {"LOW": 4, "MEDIUM": 1, "HIGH": 1, "CRITICAL": 1},
        "topV3Terms": {"REC-001": 2, "MX-REC-002": 1},
        "resolutions": {
            "apiEscalations": 2,
            "local": 4,
            "cachedApiVerdicts": 1,
        },
        "shadow": {"agreements": 5, "disagreements": 2},
    }


def _telemetry_payload_v2():
    return {
        **_telemetry_payload(),
        "schemaVersion": 2,
        "interventions": {
            "observed": 7,
            "recruiterActions": {
                "ALLOW": 4,
                "SILENT_OBSERVE": 1,
                "SOFT_WARN": 1,
                "HARD_BLOCK": 1,
            },
            "protectiveActions": {
                "SHADOW_FLAG": 2,
                "WARN_MINOR": 2,
                "PRESERVE_EVIDENCE": 1,
            },
        },
    }


def _telemetry_payload_v3():
    payload = _telemetry_payload_v2()
    payload["schemaVersion"] = 3
    payload["shadow"]["models"] = {
        "sentinel-linear-sv2-reviewed-185": {
            "featureSchemaVersion": 2,
            "agreements": 5,
            "disagreements": 2,
        }
    }
    return payload


def test_telemetry_requires_authentication(client):
    response = client.post("/api/v1/telemetry", json=_telemetry_payload())
    assert response.status_code == 401


def test_telemetry_token_requires_authentication(client):
    response = client.post("/api/v1/telemetry/token")
    assert response.status_code == 401


def test_telemetry_rejects_long_lived_api_key_in_query(client, client_key):
    response = client.post(
        "/api/v1/telemetry",
        params={"api_key": client_key},
        json=_telemetry_payload(),
    )
    assert response.status_code == 401


def test_telemetry_persists_only_aggregates(client, client_key, db_session):
    before = db_session.query(TelemetrySnapshot).count()
    response = client.post(
        "/api/v1/telemetry",
        json=_telemetry_payload(),
        headers={"X-API-Key": client_key},
    )
    assert response.status_code == 202
    assert response.json()["data"]["accepted"] is True
    db_session.expire_all()
    assert db_session.query(TelemetrySnapshot).count() == before + 1
    stored = db_session.query(TelemetrySnapshot).order_by(TelemetrySnapshot.created_at.desc()).first()
    assert stored.total_analyses == 7
    assert json.loads(stored.v3_term_counts) == {"MX-REC-002": 1, "REC-001": 2}
    assert not hasattr(stored, "message_content")
    db_session.delete(stored)
    db_session.commit()


def test_telemetry_accepts_send_beacon_shape(client, client_key, db_session):
    before = db_session.query(TelemetrySnapshot).count()
    token_response = client.post(
        "/api/v1/telemetry/token",
        headers={"X-API-Key": client_key},
    )
    assert token_response.status_code == 200
    token = token_response.json()["data"]["token"]
    response = client.post(
        "/api/v1/telemetry",
        params={"telemetry_token": token},
        content=json.dumps(_telemetry_payload()),
        headers={"Content-Type": "text/plain;charset=UTF-8"},
    )
    assert response.status_code == 202
    stored = db_session.query(TelemetrySnapshot).order_by(TelemetrySnapshot.created_at.desc()).first()
    assert db_session.query(TelemetrySnapshot).count() == before + 1
    db_session.delete(stored)
    db_session.commit()


def test_telemetry_v2_persists_recommended_interventions(
    client, client_key, db_session
):
    response = client.post(
        "/api/v1/telemetry",
        json=_telemetry_payload_v2(),
        headers={"X-API-Key": client_key},
    )
    assert response.status_code == 202
    stored = (
        db_session.query(TelemetrySnapshot)
        .order_by(TelemetrySnapshot.created_at.desc())
        .first()
    )
    assert stored.intervention_observed_count == 7
    assert stored.hard_block_count == 1
    assert json.loads(stored.protective_action_counts)["WARN_MINOR"] == 2
    db_session.delete(stored)
    db_session.commit()


def test_telemetry_v3_attributes_shadow_counts_to_model(
    client, client_key, db_session
):
    response = client.post(
        "/api/v1/telemetry",
        json=_telemetry_payload_v3(),
        headers={"X-API-Key": client_key},
    )
    assert response.status_code == 202
    stored = (
        db_session.query(TelemetrySnapshot)
        .order_by(TelemetrySnapshot.created_at.desc())
        .first()
    )
    model_counts = json.loads(stored.shadow_model_counts)
    assert model_counts["sentinel-linear-sv2-reviewed-185"] == {
        "featureSchemaVersion": 2,
        "agreements": 5,
        "disagreements": 2,
    }
    db_session.delete(stored)
    db_session.commit()


def test_telemetry_v3_rejects_free_text_as_shadow_model_id(client, client_key):
    payload = _telemetry_payload_v3()
    payload["shadow"]["models"] = {
        "mensaje privado del menor": {
            "featureSchemaVersion": 2,
            "agreements": 5,
            "disagreements": 2,
        }
    }
    response = client.post(
        "/api/v1/telemetry",
        json=payload,
        headers={"X-API-Key": client_key},
    )
    assert response.status_code == 422


def test_monthly_value_report_uses_only_client_aggregates(isolated_db):
    period_start = 1_750_032_000  # 2025-06-15 UTC
    client_hash = "c" * 64
    isolated_db.add_all(
        [
            TelemetrySnapshot(
                id=str(uuid.uuid4()),
                api_key_hash=client_hash,
                created_at=period_start,
                purge_at=period_start + 1000,
                total_analyses=7,
                low_count=4,
                medium_count=1,
                high_count=1,
                critical_count=1,
                v3_term_counts="{}",
                api_escalations=2,
                local_resolutions=4,
                cached_api_verdicts=1,
                shadow_agreements=0,
                shadow_disagreements=0,
                intervention_observed_count=7,
                allow_count=4,
                silent_observe_count=1,
                soft_warn_count=1,
                hard_block_count=1,
                protective_action_counts=json.dumps({"WARN_MINOR": 2}),
            ),
            TelemetrySnapshot(
                id=str(uuid.uuid4()),
                api_key_hash="d" * 64,
                created_at=period_start,
                purge_at=period_start + 1000,
                total_analyses=999,
                low_count=999,
                medium_count=0,
                high_count=0,
                critical_count=0,
                v3_term_counts="{}",
                api_escalations=0,
                local_resolutions=999,
                cached_api_verdicts=0,
                shadow_agreements=0,
                shadow_disagreements=0,
                intervention_observed_count=0,
                allow_count=0,
                silent_observe_count=0,
                soft_warn_count=0,
                hard_block_count=0,
                protective_action_counts="{}",
            ),
            DatasetVersion(
                created_at=period_start,
                description="monthly release",
                terms_snapshot=json.dumps(
                    [{"id": "HOT-001", "term": "termino", "category": "reclutamiento"}]
                ),
                status="published",
            ),
        ]
    )
    isolated_db.commit()

    report = build_monthly_value_report(
        isolated_db, client_hash, "Cliente <seguro>", 2025, 6
    )
    rendered = render_monthly_value_html(report)

    assert report["analyses"]["total"] == 7
    assert report["interventions"]["recruiter_actions_recommended"]["HARD_BLOCK"] == 1
    assert report["interventions"]["execution_tracking"]["available"] is False
    assert report["dataset"]["new_terms_count"] == 1
    assert "Cliente &lt;seguro&gt;" in rendered
    assert "acciones ejecutadas" in rendered


def test_monthly_value_report_requires_authentication(client):
    assert client.get("/api/v1/value-report/monthly").status_code == 401


def test_telemetry_token_is_short_lived_and_rejects_tampering():
    key_hash = "a" * 64
    token, expires_at = issue_telemetry_token(key_hash, now=1_000)
    assert expires_at == 1_300
    assert verify_telemetry_token(token, now=1_299) == key_hash
    assert verify_telemetry_token(token, now=1_300) is None
    assert verify_telemetry_token(f"{token[:-1]}x", now=1_100) is None


def test_cors_allows_only_explicit_platform_origins():
    cors_app = FastAPI()
    configure_cors(cors_app, ["https://cliente.example"])

    @cors_app.post("/telemetry")
    def telemetry_probe():
        return {"ok": True}

    with TestClient(cors_app) as cors_client:
        allowed = cors_client.options(
            "/telemetry",
            headers={
                "Origin": "https://cliente.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-api-key,content-type",
            },
        )
        denied = cors_client.options(
            "/telemetry",
            headers={
                "Origin": "https://malicioso.example",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://cliente.example"
    assert "access-control-allow-origin" not in denied.headers


def test_cors_rejects_wildcard_configuration():
    with pytest.raises(ValueError, match="wildcard"):
        configure_cors(FastAPI(), ["*"])


def test_feedback_records_authenticated_provenance_and_deduplicates(
    client, client_key, db_session
):
    session_id = f"feedback-{uuid.uuid4()}"
    payload = {
        "session_id": session_id,
        "verdict_original": {"risk": "MEDIUM"},
        "feedback": "false_positive",
        "comment": "contexto revisado",
        "reported_by": "valor-no-confiable",
        "term_ids": ["REC-001"],
        "dataset_version": 3,
    }
    first = client.post(
        "/api/v1/feedback", json=payload, headers={"X-API-Key": client_key}
    )
    second = client.post(
        "/api/v1/feedback", json=payload, headers={"X-API-Key": client_key}
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["data"]["deduplicated"] is True
    rows = db_session.query(Feedback).filter(Feedback.session_id == session_id).all()
    assert len(rows) == 1
    assert rows[0].api_key_hash == hash_api_key(client_key)
    assert rows[0].dataset_version == 3
    assert json.loads(rows[0].term_ids) == ["REC-001"]
    db_session.delete(rows[0])
    db_session.commit()


def _feedback_row(index, client_hash, term_id, base_version, feedback_type="false_positive"):
    return Feedback(
        id=f"cal-feedback-{uuid.uuid4()}-{index}",
        session_id=f"cal-session-{client_hash}-{index}",
        verdict_original="{}",
        feedback_type=feedback_type,
        comment=None,
        reported_by="ignored",
        created_at=1_999_999_900 + index,
        api_key_hash=client_hash,
        dataset_version=base_version,
        term_ids=json.dumps([term_id]),
        feedback_fingerprint=hashlib.sha256(
            f"{client_hash}-{term_id}-{index}".encode()
        ).hexdigest(),
    )


def _calibration_base(isolated_db):
    term = HotTerm(
        id=str(uuid.uuid4()),
        term=f"calibrable-{uuid.uuid4()}",
        category="reclutamiento",
        weight=10,
        initial_weight=10,
        variants=None,
        source="test",
        approved=True,
        staged=False,
        reviewed=True,
        created_at=1_999_999_000,
    )
    version = DatasetVersion(
        created_at=1_999_999_000,
        description="base",
        terms_snapshot="[]",
        status="published",
    )
    isolated_db.add_all([term, version])
    isolated_db.commit()
    return term, version


def test_calibration_ignores_manipulation_from_one_api_key(isolated_db):
    term, version = _calibration_base(isolated_db)
    isolated_db.add_all(
        [_feedback_row(i, "a" * 64, term.id, version.version) for i in range(50)]
    )
    isolated_db.commit()

    result = generate_calibration_proposal(isolated_db, now=2_000_000_000)

    assert result["status"] == "no_adjustments"
    assert result["audit"][term.id]["decision"] == "ignored_insufficient_diversity"
    assert term.weight == 10
    assert isolated_db.query(DatasetVersion).count() == 1


def test_calibration_creates_idempotent_proposal_without_applying_it(isolated_db):
    term, version = _calibration_base(isolated_db)
    rows = []
    for client_index, client_hash in enumerate(["a" * 64, "b" * 64, "c" * 64]):
        rows.extend(
            _feedback_row(i + (client_index * 20), client_hash, term.id, version.version)
            for i in range(20)
        )
    isolated_db.add_all(rows)
    isolated_db.commit()

    first = generate_calibration_proposal(isolated_db, now=2_000_000_000)
    second = generate_calibration_proposal(isolated_db, now=2_000_000_000)

    assert first["status"] == "proposal_created"
    assert second["status"] == "already_exists"
    assert first["proposal_version"] == second["proposal_version"]
    assert term.weight == 10
    assert isolated_db.query(DatasetVersion).count() == 2

    assert apply_calibration_proposal(isolated_db, first["proposal_version"]) == "applied"
    isolated_db.refresh(term)
    assert term.weight == 9


def test_candidate_prefilter_requires_two_distinct_sources(isolated_db):
    term = "vocablomultifuente"
    isolated_db.add_all(
        [
            CandidateSighting(
                id=str(uuid.uuid4()),
                term=term,
                source="fuente-a",
                context="contexto cartel",
                seen_at=100 + index,
            )
            for index in range(3)
        ]
    )
    isolated_db.commit()
    assert get_mature_candidates(isolated_db) == []

    isolated_db.add(
        CandidateSighting(
            id=str(uuid.uuid4()),
            term=term,
            source="fuente-b",
            context="otro contexto",
            seen_at=200,
        )
    )
    isolated_db.commit()
    assert [candidate["term"] for candidate in get_mature_candidates(isolated_db)] == [term]
    assert is_hard_filtered("123abc") is True
    assert is_hard_filtered("https://ejemplo.mx") is True
    assert is_hard_filtered("para") is True


def test_batch_discards_omitted_and_invented_terms(isolated_db, caplog):
    candidates = [
        {"term": "termino-uno", "source": "a", "context": "ctx"},
        {"term": "termino-dos", "source": "b", "context": "ctx"},
    ]
    response_payload = {
        "results": [
            {
                "term": "termino-uno",
                "is_risk_slang": True,
                "category": "reclutamiento",
                "weight": 7,
                "variants": [],
                "reasoning": "válido",
            },
            {
                "term": "inventado",
                "is_risk_slang": True,
                "category": "reclutamiento",
                "weight": 9,
                "variants": [],
                "reasoning": "no solicitado",
            },
        ]
    }
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response_payload)))]
    )
    captured_request = {}

    def complete(**kwargs):
        captured_request.update(kwargs)
        return completion

    groq_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=complete)
        )
    )
    with patch("src.services.hot_terms_service.Groq", return_value=groq_client):
        results = classify_terms_batch(isolated_db, candidates)

    assert len(results) == 2
    assert results[0]["staged"] is True
    assert results[1]["approved"] is False
    assert results[1]["omitted"] is True
    assert isolated_db.query(HotTerm).count() == 1
    assert "omitted" in caplog.text.lower()
    assert "invented" in caplog.text.lower()
    assert [message["role"] for message in captured_request["messages"]] == [
        "system",
        "user",
    ]


def test_batch_rejects_more_than_twenty_five_candidates(isolated_db):
    with pytest.raises(ValueError, match="at most 25"):
        classify_terms_batch(
            isolated_db,
            [
                {"term": f"terminolargo{chr(97 + index % 26)}", "source": "a"}
                for index in range(26)
            ],
        )


def test_scraper_prefilter_reduces_batch_volume_without_external_network(isolated_db):
    multi_source = "terminomultifuente"
    single_source = "terminounafuente"
    scraped = [
        {"term": multi_source, "source": "fuente-a", "context": "cartel contexto"},
        {"term": multi_source, "source": "fuente-b", "context": "otro contexto"},
        {"term": single_source, "source": "fuente-a", "context": "solo una fuente"},
        {"term": "123abc", "source": "fuente-a", "context": "número"},
    ]
    captured = []

    def fake_batch(_db, candidates):
        captured.extend(candidates)
        return [{"term": candidate["term"], "staged": True} for candidate in candidates]

    with (
        patch("src.services.scraper_service._scrape_reddit", return_value=scraped),
        patch("src.services.scraper_service._scrape_borderland_beat", return_value=[]),
        patch("src.services.scraper_service._scrape_youtube", return_value=[]),
        patch("src.services.scraper_service._scrape_lyrics", return_value=[]),
        patch("src.services.scraper_service._scrape_news_rss", return_value=[]),
        patch("src.services.scraper_service.classify_terms_batch", side_effect=fake_batch),
    ):
        result = run_scraper(isolated_db)

    assert [candidate["term"] for candidate in captured] == [multi_source]
    assert result["candidates_found"] == 4
    assert result["candidates_prefiltered"] == 1
    assert result["candidates_classified"] == 1
    assert result["terms_staged"] == 1


def _isolated_admin_client(isolated_db):
    isolated_app = FastAPI()
    isolated_app.include_router(
        admin_router,
        prefix="/admin",
        dependencies=[Depends(require_admin_key)],
    )
    isolated_app.include_router(hot_terms_router, prefix="/api/v1/hot-terms")

    def isolated_session():
        yield isolated_db

    isolated_app.dependency_overrides[get_db] = isolated_session
    isolated_app.dependency_overrides[require_admin_key] = lambda: SimpleNamespace(
        scope="admin"
    )
    return TestClient(isolated_app)


def test_admin_dashboard_review_then_versioned_publish(isolated_db):
    term = HotTerm(
        id=str(uuid.uuid4()),
        term="terminodashboard",
        category="reclutamiento",
        weight=8,
        initial_weight=8,
        variants=None,
        source="fuente-prueba",
        approved=False,
        staged=True,
        reviewed=False,
        created_at=2_000_000_000,
    )
    isolated_db.add_all(
        [
            term,
            CandidateSighting(
                id=str(uuid.uuid4()),
                term=term.term,
                source="fuente-prueba",
                context="contexto donde fue observado",
                seen_at=2_000_000_001,
            ),
        ]
    )
    isolated_db.commit()
    dashboard_client = _isolated_admin_client(isolated_db)

    page = dashboard_client.get("/admin/review")
    staged = dashboard_client.get("/admin/api/staged")
    reviewed = dashboard_client.post(f"/admin/api/staged/{term.id}/approve")

    assert page.status_code == 200
    assert "no-store" in page.headers["cache-control"]
    assert "cdn.tailwindcss.com" not in page.text
    assert staged.json()["data"][0]["context"] == "contexto donde fue observado"
    assert reviewed.status_code == 200
    isolated_db.refresh(term)
    assert term.reviewed is True
    assert term.staged is True
    assert term.approved is False

    published = dashboard_client.post("/api/v1/hot-terms/publish")
    isolated_db.refresh(term)
    assert published.status_code == 200
    assert term.approved is True
    assert term.staged is False
    assert isolated_db.query(DatasetVersion).count() == 1


def test_pipeline_stats_reports_latest_scraper_funnel(isolated_db):
    isolated_db.add(
        ScraperRun(
            id=str(uuid.uuid4()),
            started_at=100,
            finished_at=101,
            status="success",
            results=json.dumps(
                {
                    "candidates_found": 20,
                    "candidates_prefiltered": 4,
                    "candidates_classified": 4,
                    "terms_staged": 2,
                    "terms_omitted": 1,
                }
            ),
        )
    )
    isolated_db.commit()

    latest = get_pipeline_stats(isolated_db)["ultima_corrida"]
    assert latest == {
        "candidatos_entraron": 20,
        "candidatos_sobrevivieron_prefiltro": 4,
        "candidatos_clasificados": 4,
        "candidatos_aprobados_ia": 2,
        "candidatos_omitidos_por_llm": 1,
    }


def test_telemetry_rejects_free_text_disguised_as_term_id(client, client_key):
    payload = _telemetry_payload()
    payload["topV3Terms"] = {"manda tu ubicacion completa": 1}
    response = client.post(
        "/api/v1/telemetry",
        json=payload,
        headers={"X-API-Key": client_key},
    )
    assert response.status_code == 422
