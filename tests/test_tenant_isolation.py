import os
import sys
import time
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from src.database import get_db, Base
from src.models.db_models import (
    ApiKey,
    Session as ChatSession,
    Message as DBMessage,
    AnalysisRecord,
    EvidencePackage,
    TelemetrySnapshot,
    ActorSighting,
)
from src.core.security import hash_api_key
from src.services.telemetry_token import issue_telemetry_token


@pytest.fixture
def isolation_env():
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    TestingSession = sessionmaker(bind=test_engine)
    db = TestingSession()

    # Seed API keys
    key_client_a = "sentinel_client_a_secret_key_12345"
    key_client_b = "sentinel_client_b_secret_key_67890"
    key_admin = "sentinel_admin_secret_key_99999"
    key_revoked = "sentinel_revoked_client_key_00000"

    hash_a = hash_api_key(key_client_a)
    hash_b = hash_api_key(key_client_b)
    hash_admin = hash_api_key(key_admin)
    hash_revoked = hash_api_key(key_revoked)

    now = int(time.time())
    db.add_all([
        ApiKey(key_hash=hash_a, name="Client Organization A", scope="client", created_at=now),
        ApiKey(key_hash=hash_b, name="Client Organization B", scope="client", created_at=now),
        ApiKey(key_hash=hash_admin, name="Admin Root", scope="admin", created_at=now),
        ApiKey(key_hash=hash_revoked, name="Revoked Client", scope="client", created_at=now, revoked_at=now - 100),
    ])
    db.commit()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield {
            "client": client,
            "db": db,
            "key_a": key_client_a,
            "hash_a": hash_a,
            "key_b": key_client_b,
            "hash_b": hash_b,
            "key_admin": key_admin,
            "hash_admin": hash_admin,
            "key_revoked": key_revoked,
        }

    app.dependency_overrides.pop(get_db, None)
    db.close()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def test_messages_and_sessions_isolation_same_session_id(isolation_env):
    """
    Dos clientes sincronizan mensajes usando el MISMO session_id ('sess-shared-100').
    Cada uno debe recibir estrictamente su propio historial sin cruces ni fugas.
    """
    client = isolation_env["client"]
    key_a = isolation_env["key_a"]
    key_b = isolation_env["key_b"]

    shared_session = "sess-shared-100"

    # Cliente A sincroniza mensaje 1
    res_a1 = client.post(
        "/api/v1/messages/sync",
        headers={"X-API-Key": key_a},
        json={
            "message": {
                "session_id": shared_session,
                "user_id": "user-client-a",
                "content": "Mensaje confidencial de Cliente A",
                "timestamp": 1000,
            }
        },
    )
    assert res_a1.status_code == 200
    data_a1 = res_a1.json()["data"]
    assert len(data_a1) == 1
    assert data_a1[0]["content"] == "Mensaje confidencial de Cliente A"

    # Cliente B sincroniza mensaje 1 en el mismo session_id
    res_b1 = client.post(
        "/api/v1/messages/sync",
        headers={"X-API-Key": key_b},
        json={
            "message": {
                "session_id": shared_session,
                "user_id": "user-client-b",
                "content": "Mensaje privado de Cliente B",
                "timestamp": 1050,
            }
        },
    )
    assert res_b1.status_code == 200
    data_b1 = res_b1.json()["data"]
    # Cliente B NO debe ver el mensaje de Cliente A
    assert len(data_b1) == 1
    assert data_b1[0]["content"] == "Mensaje privado de Cliente B"

    # Cliente A sincroniza mensaje 2
    res_a2 = client.post(
        "/api/v1/messages/sync",
        headers={"X-API-Key": key_a},
        json={
            "message": {
                "session_id": shared_session,
                "user_id": "user-client-a",
                "content": "Segundo mensaje de Cliente A",
                "timestamp": 1100,
            }
        },
    )
    assert res_a2.status_code == 200
    data_a2 = res_a2.json()["data"]
    # Cliente A debe ver sus 2 mensajes y NINGUNO de Cliente B
    assert len(data_a2) == 2
    contents_a = [m["content"] for m in data_a2]
    assert "Mensaje confidencial de Cliente A" in contents_a
    assert "Segundo mensaje de Cliente A" in contents_a
    assert "Mensaje privado de Cliente B" not in contents_a


def test_evidence_legal_hold_isolation_by_tenant(isolation_env):
    """
    Cliente A genera evidencia para una sesión. Cliente B con el mismo session_id
    recibe 404 (no puede consultar ni descargar el paquete de evidencia ajeno).
    """
    client = isolation_env["client"]
    db = isolation_env["db"]
    key_a = isolation_env["key_a"]
    hash_a = isolation_env["hash_a"]
    key_b = isolation_env["key_b"]

    shared_session = "sess-evidence-200"
    now = int(time.time())

    # Registrar análisis HIGH de Cliente A
    db.add(AnalysisRecord(
        id=str(uuid.uuid4()),
        session_id=shared_session,
        api_key_hash=hash_a,
        risk="HIGH",
        analysis_payload='{"messages":[{"id":"m1","session_id":"sess-evidence-200","user_id":"u1","content":"hay jale","timestamp":100}]}',
        llm_verdict='{"stage":"CAPTACION","risk":"HIGH"}',
        dataset_versions='{"sdk_region_packs":{},"api_hot_terms":null}',
        created_at=now,
        purge_at=now + 604800,
    ))
    db.commit()

    # Cliente A genera paquete de evidencia -> 200 OK
    res_ev_a = client.post(f"/api/v1/evidence/{shared_session}", headers={"X-API-Key": key_a})
    assert res_ev_a.status_code == 200
    assert res_ev_a.json()["payload"]["session_id"] == shared_session

    # Cliente B intenta acceder al paquete de evidencia de la misma sesión -> 404 Not Found
    res_ev_b = client.post(f"/api/v1/evidence/{shared_session}", headers={"X-API-Key": key_b})
    assert res_ev_b.status_code == 404


def test_network_actor_isolation_no_cross_tenant_recidivism(isolation_env):
    """
    Cliente A y Cliente B reportan un agresor con el mismo user_id ('aggressor-999').
    El hashing con salt por tenant debe evitar que los avistamientos se mezclen
    o correlacionen erróneamente entre distintas organizaciones.
    """
    client = isolation_env["client"]
    key_a = isolation_env["key_a"]
    key_b = isolation_env["key_b"]

    guion = ["tengo un jale para ti, te paso a buscar"]

    # Cliente A reporta sesión 1 del agresor
    res_a1 = client.post(
        "/api/v1/network/report",
        headers={"X-API-Key": key_a},
        json={
            "aggressor_user_id": "aggressor-999",
            "session_id": "sess-a-1",
            "aggressor_texts": guion,
            "risk": "HIGH",
            "categories": ["reclutamiento"],
        },
    )
    assert res_a1.status_code == 200
    assert res_a1.json()["data"]["distinct_sessions"] == 1
    assert res_a1.json()["data"]["actor_risk"] == "NONE"

    # Cliente B reporta a "aggressor-999" en su propia sesión
    res_b1 = client.post(
        "/api/v1/network/report",
        headers={"X-API-Key": key_b},
        json={
            "aggressor_user_id": "aggressor-999",
            "session_id": "sess-b-1",
            "aggressor_texts": guion,
            "risk": "HIGH",
            "categories": ["reclutamiento"],
        },
    )
    assert res_b1.status_code == 200
    # No debe haber reincidencia cruzada entre tenants: distinct_sessions debe ser 1 para Cliente B
    assert res_b1.json()["data"]["distinct_sessions"] == 1
    assert res_b1.json()["data"]["actor_risk"] == "NONE"

    # Cliente A reporta una segunda sesión del agresor
    res_a2 = client.post(
        "/api/v1/network/report",
        headers={"X-API-Key": key_a},
        json={
            "aggressor_user_id": "aggressor-999",
            "session_id": "sess-a-2",
            "aggressor_texts": guion,
            "risk": "HIGH",
            "categories": ["reclutamiento"],
        },
    )
    assert res_a2.status_code == 200
    # Dentro del espacio de Cliente A, ahora sí hay 2 sesiones distintas
    assert res_a2.json()["data"]["distinct_sessions"] == 2
    assert "RECIDIVISM" in res_a2.json()["data"]["signals"]


def test_feedback_submission_and_tenant_partitioning(isolation_env):
    """
    El feedback recibido se etiqueta con el api_key_hash del cliente y
    su fingerprint es único por tenant.
    """
    client = isolation_env["client"]
    db = isolation_env["db"]
    key_a = isolation_env["key_a"]
    hash_a = isolation_env["hash_a"]

    res = client.post(
        "/api/v1/feedback",
        headers={"X-API-Key": key_a},
        json={
            "session_id": "sess-fb-1",
            "verdict_original": {"risk": "MEDIUM", "stage": "SONDEO"},
            "feedback": "confirmed",
            "reported_by": "moderator_1",
            "term_ids": ["REC-001"],
            "dataset_version": 1,
        },
    )
    assert res.status_code == 201
    feedback_id = res.json()["data"]["id"]

    # Verificar en DB que se asoció al tenant A
    from src.models.db_models import Feedback
    fb_row = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    assert fb_row is not None
    assert fb_row.api_key_hash == hash_a


def test_value_report_isolation_by_tenant(isolation_env):
    """
    El reporte mensual de valor agrega únicamente los análisis del tenant que lo consulta.
    """
    client = isolation_env["client"]
    db = isolation_env["db"]
    key_a = isolation_env["key_a"]
    hash_a = isolation_env["hash_a"]
    key_b = isolation_env["key_b"]
    hash_b = isolation_env["hash_b"]

    now = int(time.time())
    # Ingestar snapshot de Cliente A (100 análisis)
    db.add(TelemetrySnapshot(
        id=str(uuid.uuid4()),
        api_key_hash=hash_a,
        created_at=now,
        purge_at=now + 7776000,
        total_analyses=100,
        low_count=80,
        medium_count=15,
        high_count=4,
        critical_count=1,
        v3_term_counts="{}",
        api_escalations=20,
        local_resolutions=80,
        cached_api_verdicts=0,
        shadow_agreements=0,
        shadow_disagreements=0,
    ))
    # Ingestar snapshot de Cliente B (500 análisis)
    db.add(TelemetrySnapshot(
        id=str(uuid.uuid4()),
        api_key_hash=hash_b,
        created_at=now,
        purge_at=now + 7776000,
        total_analyses=500,
        low_count=400,
        medium_count=80,
        high_count=15,
        critical_count=5,
        v3_term_counts="{}",
        api_escalations=100,
        local_resolutions=400,
        cached_api_verdicts=0,
        shadow_agreements=0,
        shadow_disagreements=0,
    ))
    db.commit()

    # Reporte de Cliente A
    res_rep_a = client.get("/api/v1/value-report/monthly", headers={"X-API-Key": key_a})
    assert res_rep_a.status_code == 200
    assert res_rep_a.json()["data"]["analyses"]["total"] == 100

    # Reporte de Cliente B
    res_rep_b = client.get("/api/v1/value-report/monthly", headers={"X-API-Key": key_b})
    assert res_rep_b.status_code == 200
    assert res_rep_b.json()["data"]["analyses"]["total"] == 500


def test_revoked_key_rejected(isolation_env):
    """Una clave revocada recibe 401 en todos los endpoints."""
    client = isolation_env["client"]
    key_revoked = isolation_env["key_revoked"]

    res_sync = client.post(
        "/api/v1/messages/sync",
        headers={"X-API-Key": key_revoked},
        json={"message": {"session_id": "s1", "user_id": "u1", "content": "test", "timestamp": 100}},
    )
    assert res_sync.status_code == 401
    assert "revoked" in res_sync.json()["detail"].lower()

    res_ev = client.post("/api/v1/evidence/s1", headers={"X-API-Key": key_revoked})
    assert res_ev.status_code == 401


def test_client_cannot_access_admin_routes(isolation_env):
    """Las claves con scope 'client' no pueden acceder a endpoints administrativos (403 Forbidden)."""
    client = isolation_env["client"]
    key_a = isolation_env["key_a"]
    key_admin = isolation_env["key_admin"]

    # Client intenta acceder a admin staged terms -> 403
    res_admin_staged = client.get("/admin/api/staged", headers={"X-API-Key": key_a})
    assert res_admin_staged.status_code == 403

    # Client intenta acceder a admin messages -> 403
    res_admin_msg = client.get("/api/v1/admin/messages", headers={"X-API-Key": key_a})
    assert res_admin_msg.status_code == 403

    # Admin accede correctamente -> 200
    res_ok_staged = client.get("/admin/api/staged", headers={"X-API-Key": key_admin})
    assert res_ok_staged.status_code == 200


def test_browser_admin_basic_auth_security(isolation_env):
    """
    El endpoint del panel /admin/review exige Basic Auth, nunca expone secretos en la URL
    ni incrusta la API Key en el código HTML servido.
    """
    client = isolation_env["client"]
    key_admin = isolation_env["key_admin"]

    # 1. Sin credenciales -> 401 con WWW-Authenticate
    res_unauth = client.get("/admin/review")
    assert res_unauth.status_code == 401
    assert 'Basic realm="Sentinel Admin"' in res_unauth.headers.get("WWW-Authenticate", "")

    # 2. Con Basic Auth válido -> 200 HTML con headers defensivos
    import base64
    basic_val = base64.b64encode(f"admin:{key_admin}".encode()).decode()
    res_auth = client.get("/admin/review", headers={"Authorization": f"Basic {basic_val}"})
    assert res_auth.status_code == 200
    assert "no-store" in res_auth.headers.get("Cache-Control", "")
    assert "Content-Security-Policy" in res_auth.headers
    # Comprobar que la clave admin no está incrustada en el texto del HTML
    assert key_admin not in res_auth.text
