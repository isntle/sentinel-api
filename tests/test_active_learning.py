import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database import Base
from src.models.db_models import ActiveLearningQueueItem
from src.services.active_learning_service import (
    ActiveLearningService,
    calculate_uncertainty_score,
    generate_item_fingerprint,
    MAX_ITEMS_PER_FAMILY,
)

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_uncertainty_metric_calculation():
    # p=0.5 -> max uncertainty 1.0
    assert calculate_uncertainty_score(0.5) == 1.0
    # p=0.0 or 1.0 -> min uncertainty 0.0
    assert calculate_uncertainty_score(0.0) == 0.0
    assert calculate_uncertainty_score(1.0) == 0.0
    # p=0.4 or 0.6 -> uncertainty 0.8
    assert round(calculate_uncertainty_score(0.4), 2) == 0.8
    assert round(calculate_uncertainty_score(0.6), 2) == 0.8
    # None -> 0.0
    assert calculate_uncertainty_score(None) == 0.0

def test_enqueue_disagreement_and_uncertainty(db_session):
    api_key_hash = "test_hash_org_1"
    
    # 1. Caso de desacuerdo: primary=HIGH (risky), shadow=0.1 (non-risky)
    res_disagree = ActiveLearningService.enqueue_item(
        db=db_session,
        session_id="sess_disagree_1",
        api_key_hash=api_key_hash,
        primary_verdict="HIGH",
        shadow_probability=0.1,
    )
    assert res_disagree["success"] is True
    assert res_disagree["enqueued"] is True
    assert res_disagree["sampling_strategy"] == "disagreement"
    assert res_disagree["inclusion_probability"] == 0.8
    assert res_disagree["status"] == "pending"

    # 2. Caso de incertidumbre con concordancia: primary=LOW (non-risky), shadow=0.48 (non-risky, pero cerca de 0.5)
    res_uncertain = ActiveLearningService.enqueue_item(
        db=db_session,
        session_id="sess_uncertain_1",
        api_key_hash=api_key_hash,
        primary_verdict="LOW",
        shadow_probability=0.48,
    )
    assert res_uncertain["success"] is True
    assert res_uncertain["sampling_strategy"] == "uncertainty"
    assert res_uncertain["inclusion_probability"] == 0.6

    # 3. Caso aleatorio de control
    res_random = ActiveLearningService.enqueue_item(
        db=db_session,
        session_id="sess_random_1",
        api_key_hash=api_key_hash,
        primary_verdict="LOW",
        shadow_probability=0.02,
        random_inclusion_prob=0.05,
    )
    assert res_random["success"] is True
    assert res_random["sampling_strategy"] == "random_baseline"
    assert res_random["inclusion_probability"] == 0.05

def test_idempotency_and_duplicate_prevention(db_session):
    api_key_hash = "test_hash_org_2"
    session_id = "sess_duplicate_test"

    res1 = ActiveLearningService.enqueue_item(
        db=db_session,
        session_id=session_id,
        api_key_hash=api_key_hash,
        primary_verdict="HIGH",
        shadow_probability=0.2,
    )
    assert res1["enqueued"] is True
    assert res1["deduplicated"] is False

    # Segundo reintento con mismos parámetros
    res2 = ActiveLearningService.enqueue_item(
        db=db_session,
        session_id=session_id,
        api_key_hash=api_key_hash,
        primary_verdict="HIGH",
        shadow_probability=0.2,
    )
    assert res2["success"] is True
    assert res2["enqueued"] is False
    assert res2["deduplicated"] is True
    assert res2["item_id"] == res1["item_id"]

def test_family_quota_limit(db_session):
    api_key_hash = "test_hash_org_3"
    family_id = "fam_narco_song_quotes"

    # Insertar hasta el límite MAX_ITEMS_PER_FAMILY
    for i in range(MAX_ITEMS_PER_FAMILY):
        res = ActiveLearningService.enqueue_item(
            db=db_session,
            session_id=f"sess_fam_{i}",
            api_key_hash=api_key_hash,
            primary_verdict="MEDIUM",
            shadow_probability=0.45,
            family_id=family_id,
        )
        assert res["enqueued"] is True

    # El siguiente excede la cuota de familia
    res_overflow = ActiveLearningService.enqueue_item(
        db=db_session,
        session_id="sess_fam_overflow",
        api_key_hash=api_key_hash,
        primary_verdict="MEDIUM",
        shadow_probability=0.45,
        family_id=family_id,
    )
    assert res_overflow["success"] is False
    assert res_overflow["enqueued"] is False
    assert "quota exceeded" in res_overflow["reason"]

def test_blind_review_batch_extraction(db_session):
    api_key_hash = "test_hash_org_4"
    ActiveLearningService.enqueue_item(
        db=db_session,
        session_id="sess_blind_1",
        api_key_hash=api_key_hash,
        primary_verdict="CRITICAL",
        shadow_probability=0.15,
    )

    # Modo ciego (blind=True)
    batch_blind = ActiveLearningService.get_review_batch(db=db_session, api_key_hash=api_key_hash, blind=True)
    assert len(batch_blind) == 1
    item_blind = batch_blind[0]
    assert "primary_verdict" not in item_blind
    assert "shadow_probability" not in item_blind
    assert "uncertainty_score" not in item_blind

    # Modo no ciego (blind=False) para supervisores/adjudicadores
    batch_open = ActiveLearningService.get_review_batch(db=db_session, api_key_hash=api_key_hash, blind=False)
    assert len(batch_open) == 1
    item_open = batch_open[0]
    assert item_open["primary_verdict"] == "CRITICAL"
    assert item_open["shadow_probability"] == 0.15

def test_review_progression_and_adjudication(db_session):
    api_key_hash = "test_hash_org_5"
    res = ActiveLearningService.enqueue_item(
        db=db_session,
        session_id="sess_progression_1",
        api_key_hash=api_key_hash,
        primary_verdict="MEDIUM",
        shadow_probability=0.52,
    )
    item_id = res["item_id"]

    # 1. Estado inicial es 'pending' (NUNCA aprobado o eligible)
    item = db_session.get(ActiveLearningQueueItem, item_id)
    assert item.status == "pending"

    # 2. Primera revisión humana
    rev1 = ActiveLearningService.submit_review(
        db=db_session,
        item_id=item_id,
        reviewer_id="rev_alice",
        verdict="RISK",
    )
    assert rev1["status"] == "reviewed"
    assert rev1["adjudicated_verdict"] is None

    # Mismo revisor no puede revisar dos veces
    with pytest.raises(ValueError):
        ActiveLearningService.submit_review(
            db=db_session,
            item_id=item_id,
            reviewer_id="rev_alice",
            verdict="RISK",
        )

    # 3. Segunda revisión con consenso unánime
    rev2 = ActiveLearningService.submit_review(
        db=db_session,
        item_id=item_id,
        reviewer_id="rev_bob",
        verdict="RISK",
    )
    assert rev2["status"] == "adjudicated"
    assert rev2["adjudicated_verdict"] == "RISK"

    # 4. Adjudicación formal a 'eligible' para dataset
    adj = ActiveLearningService.adjudicate_item(
        db=db_session,
        item_id=item_id,
        adjudicator_id="rev_lead_moderator",
        final_verdict="RISK",
        mark_eligible=True,
    )
    assert adj["status"] == "eligible"
    assert adj["final_verdict"] == "RISK"

def test_ipw_debiased_population_estimates(db_session):
    api_key_hash = "test_hash_org_6"

    # Simular 10 ítems en cola activa:
    # - 8 casos de alta incertidumbre/desacuerdo (prob inclusión pi = 0.8), de los cuales 6 son RISK
    # - 2 casos de muestreo aleatorio (prob inclusión pi = 0.1), de los cuales 0 son RISK
    for i in range(8):
        res = ActiveLearningService.enqueue_item(
            db=db_session,
            session_id=f"sess_enriched_{i}",
            api_key_hash=api_key_hash,
            primary_verdict="HIGH",
            shadow_probability=0.2,
        )
        ActiveLearningService.adjudicate_item(
            db=db_session,
            item_id=res["item_id"],
            adjudicator_id="rev_lead",
            final_verdict="RISK" if i < 6 else "BENIGN",
            mark_eligible=True,
        )

    for j in range(2):
        res = ActiveLearningService.enqueue_item(
            db=db_session,
            session_id=f"sess_random_{j}",
            api_key_hash=api_key_hash,
            primary_verdict="LOW",
            shadow_probability=0.01,
            random_inclusion_prob=0.1,
        )
        ActiveLearningService.adjudicate_item(
            db=db_session,
            item_id=res["item_id"],
            adjudicator_id="rev_lead",
            final_verdict="BENIGN",
            mark_eligible=True,
        )

    estimates = ActiveLearningService.calculate_debiased_population_estimates(
        db=db_session,
        api_key_hash=api_key_hash,
    )
    assert estimates["total_adjudicated"] == 10
    # Naive prevalence: 6 / 10 = 0.60 (sobreestimada por sesgo de selección de la cola)
    assert estimates["naive_risk_prevalence"] == 0.60
    # IPW prevalence:
    # weighted_risk = 6 * (1/0.8) = 7.5
    # weighted_total = 8 * (1/0.8) + 2 * (1/0.1) = 10 + 20 = 30
    # debiased = 7.5 / 30 = 0.25 (corrige el sesgo de sobremuestreo activo)
    assert estimates["ipw_debiased_risk_prevalence"] == 0.25
    assert estimates["ipw_debiased_risk_prevalence"] < estimates["naive_risk_prevalence"]

from fastapi.testclient import TestClient
from main import app
from src.database import get_db
from src.core.security import hash_api_key
from src.models.db_models import ApiKey
from sqlalchemy.pool import StaticPool

def test_active_learning_http_endpoints():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    db = TestingSession()

    client_key = "sentinel_client_key_123"
    admin_key = "sentinel_admin_key_456"

    db.add(ApiKey(key_hash=hash_api_key(client_key), name="Client Org", scope="client", created_at=1000))
    db.add(ApiKey(key_hash=hash_api_key(admin_key), name="Admin Org", scope="admin", created_at=1000))
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        # 1. Enqueue candidate (client key)
        resp_enq = client.post(
            "/api/v1/active-learning/enqueue",
            headers={"X-API-Key": client_key},
            json={
                "session_id": "sess_http_1",
                "primary_verdict": "HIGH",
                "shadow_probability": 0.2,
                "family_id": "fam_http_1",
            },
        )
        assert resp_enq.status_code == 201
        data_enq = resp_enq.json()["data"]
        item_id = data_enq["item_id"]
        assert data_enq["sampling_strategy"] == "disagreement"

        # 2. Get review queue in blind mode (admin key)
        resp_queue = client.get(
            "/api/v1/active-learning/queue?blind=true",
            headers={"X-API-Key": admin_key},
        )
        assert resp_queue.status_code == 200
        items = resp_queue.json()["data"]["items"]
        assert len(items) == 1
        assert "primary_verdict" not in items[0]

        # 3. Submit 1st review
        resp_rev1 = client.post(
            f"/api/v1/active-learning/review/{item_id}",
            headers={"X-API-Key": admin_key},
            json={"reviewer_id": "rev_moderator_1", "verdict": "RISK"},
        )
        assert resp_rev1.status_code == 200
        assert resp_rev1.json()["data"]["status"] == "reviewed"

        # 4. Adjudicate
        resp_adj = client.post(
            f"/api/v1/active-learning/adjudicate/{item_id}",
            headers={"X-API-Key": admin_key},
            json={"adjudicator_id": "rev_lead_judge", "final_verdict": "RISK", "mark_eligible": True},
        )
        assert resp_adj.status_code == 200
        assert resp_adj.json()["data"]["status"] == "eligible"

        # 5. Stats
        resp_stats = client.get(
            "/api/v1/active-learning/stats",
            headers={"X-API-Key": admin_key},
        )
        assert resp_stats.status_code == 200
        assert resp_stats.json()["data"]["total_adjudicated"] == 1

        # 6. Moderation Web UI route check
        resp_mod = client.get("/moderation")
        assert resp_mod.status_code == 200
        assert "Bandeja de Moderación" in resp_mod.text
        assert "Sentinel" in resp_mod.text
    finally:
        app.dependency_overrides.clear()
        db.close()

