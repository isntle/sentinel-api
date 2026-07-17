import pytest
import time
import hashlib
import json
import uuid
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app
from src.database import get_db, Base, engine
from sqlalchemy.orm import Session
from src.models.db_models import AnalysisRecord, ApiKey, EvidencePackage
from src.core.security import hash_api_key
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

# We override the DB dependency for tests
@pytest.fixture(scope="session")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    yield db
    # We do not drop tables because other things might be running, but in a real isolated test we would.

@pytest.fixture(scope="session")
def client():
    return TestClient(app)

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

def test_admin_key_accepted_on_client_route(client, admin_key):
    # Admin should also be able to access client routes if they use the client dependency,
    # because admin scope check in RequireKey is only for required_scope="admin".
    # Wait, our RequireKey logic currently only checks: 
    # if required == admin and scope != admin -> 403. 
    # This means admin CAN access client endpoints because required == client, and it doesn't fail.
    response = client.get("/api/v1/hot-terms", headers={"X-API-Key": admin_key})
    assert response.status_code == 200


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
