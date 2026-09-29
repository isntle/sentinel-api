import os
import sys
import uuid
import time
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import Base, get_db
from src.models.db_models import HotTerm, CandidateSighting, DataSource, DatasetVersion
from src.services.candidate_scorer import get_mature_candidates
from src.services.hot_terms_service import publish_version, approve_term_manual
from src.services.data_provenance_service import (
    ensure_canonical_data_sources,
    register_data_source,
    review_data_source,
    export_dataset_by_usage,
    calculate_content_hash,
    resolve_canonical_origin,
)
from src.models.db_models import ApiKey
from src.core.security import hash_api_key
from main import app

@pytest.fixture
def provenance_env():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()

    ensure_canonical_data_sources(db)

    admin_key = "sentinel_admin_test_secret_key"
    admin_hash = hash_api_key(admin_key)
    db.add(ApiKey(
        key_hash=admin_hash,
        name="Test Admin Key",
        scope="admin",
        created_at=int(time.time()),
    ))
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    yield {
        "db": db,
        "client": client,
        "engine": engine,
        "admin_key": admin_key,
    }

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    db.close()


def test_deduplication_different_urls_same_origin_and_content(provenance_env):
    """
    Dos URLs distintas del mismo medio o con el mismo texto no cuentan como dos
    fuentes independientes; la maduración requiere orígenes y contenidos distintos.
    """
    db = provenance_env["db"]
    now = int(time.time())

    # Sighting 1 de Río Doce URL 1
    db.add(CandidateSighting(
        id=str(uuid.uuid4()),
        term="puntero_sinaloa",
        source="https://riodoce.mx/noticias/post-101",
        canonical_origin="riodoce.mx",
        content_hash=calculate_content_hash("reportan actividad de halcones y punteros en culiacan"),
        context="reportan actividad de halcones y punteros en culiacan",
        seen_at=now,
    ))
    # Sighting 2 de Río Doce URL 2 (mismo medio, mismo texto duplicado)
    db.add(CandidateSighting(
        id=str(uuid.uuid4()),
        term="puntero_sinaloa",
        source="https://riodoce.mx/espejo/post-101-mirror",
        canonical_origin="riodoce.mx",
        content_hash=calculate_content_hash("reportan actividad de halcones y punteros en culiacan"),
        context="reportan actividad de halcones y punteros en culiacan",
        seen_at=now + 10,
    ))
    db.commit()

    # No debe madurar porque solo hay 1 origen canónico y 1 hash de contenido
    mature = get_mature_candidates(db)
    assert not any(c["term"] == "puntero_sinaloa" for c in mature)

    # Añadimos sighting 3 de una fuente independiente (Borderland Beat) con contenido distinto
    db.add(CandidateSighting(
        id=str(uuid.uuid4()),
        term="puntero_sinaloa",
        source="https://borderlandbeat.com/2026/09/investigation.html",
        canonical_origin="borderlandbeat.com",
        content_hash=calculate_content_hash("independent analysis shows punteros operating in coordinates"),
        context="independent analysis shows punteros operating in coordinates",
        seen_at=now + 20,
    ))
    db.commit()

    # Ahora sí madura: 2 orígenes canónicos distintos y 2 contenidos distintos
    mature_after = get_mature_candidates(db)
    assert any(c["term"] == "puntero_sinaloa" for c in mature_after)


def test_unreviewed_terms_cannot_be_published(provenance_env):
    """
    Un término evaluado por IA pero no revisado por un humano (reviewed=False)
    jamás puede ser publicado en una versión de dataset.
    """
    db = provenance_env["db"]
    now = int(time.time())

    # Término staged por IA pero sin revisión humana
    unreviewed_term = HotTerm(
        id=str(uuid.uuid4()),
        term="jale_turbio",
        category="reclutamiento",
        weight=8.0,
        source="Reddit r/Narco",
        canonical_origin="reddit.com",
        content_hash=calculate_content_hash("jale_turbio"),
        staged=True,
        reviewed=False, # NO revisado por humano
        approved=False,
        created_at=now,
    )
    db.add(unreviewed_term)
    db.commit()

    # Intentar publicar
    version = publish_version(db, description="Intento sin revisión")
    assert version is None # No debe publicar nada

    # Ahora un humano revisa y aprueba el término
    success = approve_term_manual(db, unreviewed_term.id)
    assert success is True

    # Intentar publicar nuevamente
    version_published = publish_version(db, description="Publicación aprobada")
    assert version_published is not None
    assert version_published.version == 1

    # Verificar que el término ahora está aprobado
    db.refresh(unreviewed_term)
    assert unreviewed_term.approved is True
    assert unreviewed_term.staged is False


def test_legacy_unknown_permissions_excluded_from_training_export(provenance_env):
    """
    Términos con origen histórico desconocido o sin trazabilidad se excluyen
    del export de entrenamiento.
    """
    db = provenance_env["db"]
    now = int(time.time())

    # Término heredado sin permisos verificables
    db.add(HotTerm(
        id=str(uuid.uuid4()),
        term="termino_antiguo_1990",
        category="desconocida",
        weight=2.0,
        source="legacy_unknown",
        source_id="src_legacy_seed",
        canonical_origin="sentinel_legacy_corpus",
        content_hash=calculate_content_hash("termino_antiguo_1990"),
        approved=True,
        reviewed=True,
        created_at=now,
    ))
    # Término con rúbrica mexicana aprobada
    db.add(HotTerm(
        id=str(uuid.uuid4()),
        term="halconeo_organizado",
        category="reclutamiento",
        weight=10.0,
        source="Panel de Expertos",
        source_id="src_expert_curated_mexican_rubric",
        canonical_origin="sentinel_expert_panel",
        content_hash=calculate_content_hash("halconeo_organizado"),
        approved=True,
        reviewed=True,
        created_at=now,
    ))
    db.commit()

    # Export para entrenamiento
    manifest = export_dataset_by_usage(db, target_use="training")
    assert manifest["target_use"] == "training"
    assert manifest["total_terms_examined"] >= 2

    exported_terms = [item["term"] for item in manifest["items"]]
    assert "halconeo_organizado" in exported_terms
    assert "termino_antiguo_1990" not in exported_terms
    assert manifest["exclusions_breakdown"]["unknown_permissions"] >= 1


def test_quarantined_and_revoked_sources_excluded(provenance_env):
    """
    Fuentes en cuarentena o revocadas no pueden exportar datos para entrenamiento.
    """
    db = provenance_env["db"]
    now = int(time.time())

    # 1. Registrar fuente en cuarentena
    register_data_source(
        db=db,
        source_id="src_unverified_forum",
        name="Foro No Verificado",
        canonical_origin="darkforum.net",
        source_type="public_dataset",
        license_ref="none_provided",
        allowed_uses=["discovery", "training"],
        permission_status="quarantine",
    )
    db.add(HotTerm(
        id=str(uuid.uuid4()),
        term="jerga_cuarentena",
        category="reclutamiento",
        weight=5.0,
        source_id="src_unverified_forum",
        canonical_origin="darkforum.net",
        approved=True,
        reviewed=True,
        created_at=now,
    ))

    # 2. Registrar fuente revocada
    register_data_source(
        db=db,
        source_id="src_revoked_partner",
        name="Partner Revocado",
        canonical_origin="revokedpartner.org",
        source_type="expert_annotation",
        license_ref="revoked_mou_2025",
        allowed_uses=["training"],
        permission_status="revoked",
    )
    db.add(HotTerm(
        id=str(uuid.uuid4()),
        term="jerga_revocada",
        category="reclutamiento",
        weight=5.0,
        source_id="src_revoked_partner",
        canonical_origin="revokedpartner.org",
        approved=True,
        reviewed=True,
        created_at=now,
    ))
    db.commit()

    manifest = export_dataset_by_usage(db, target_use="training")
    exported_terms = [item["term"] for item in manifest["items"]]

    assert "jerga_cuarentena" not in exported_terms
    assert "jerga_revocada" not in exported_terms
    assert manifest["exclusions_breakdown"]["quarantined_source"] >= 1
    assert manifest["exclusions_breakdown"]["revoked_source"] >= 1


def test_rights_differentiation_discovery_vs_training_vs_redistribution(provenance_env):
    """
    Reddit (solo discovery) se permite en export de descubrimiento pero se bloquea
    en entrenamiento y redistribución. Datos sintéticos CC-BY se permiten en todos.
    """
    db = provenance_env["db"]
    now = int(time.time())

    # Término de Reddit (allowed_uses="discovery")
    db.add(HotTerm(
        id=str(uuid.uuid4()),
        term="palabra_reddit",
        category="sondeo",
        weight=4.0,
        source_id="src_reddit_discovery",
        canonical_origin="reddit.com",
        approved=True,
        reviewed=True,
        created_at=now,
    ))
    # Término Sintético Contrastivo (allowed_uses="discovery,training,evaluation,redistribution")
    db.add(HotTerm(
        id=str(uuid.uuid4()),
        term="par_sintetico_mex",
        category="reclutamiento",
        weight=9.0,
        source_id="src_synthetic_contrastive_mexican",
        canonical_origin="sentinel_synthetic_pipeline",
        approved=True,
        reviewed=True,
        created_at=now,
    ))
    db.commit()

    # 1. Export para discovery
    discovery_manifest = export_dataset_by_usage(db, target_use="discovery")
    discovery_terms = [item["term"] for item in discovery_manifest["items"]]
    assert "palabra_reddit" in discovery_terms
    assert "par_sintetico_mex" in discovery_terms

    # 2. Export para training
    training_manifest = export_dataset_by_usage(db, target_use="training")
    training_terms = [item["term"] for item in training_manifest["items"]]
    assert "palabra_reddit" not in training_terms  # Bloqueado: Reddit es discovery_only
    assert "par_sintetico_mex" in training_terms   # Permitido: synthetic tiene training rights
    assert training_manifest["exclusions_breakdown"]["unauthorized_usage_rights"] >= 1

    # 3. Export para redistribution
    redist_manifest = export_dataset_by_usage(db, target_use="redistribution")
    redist_terms = [item["term"] for item in redist_manifest["items"]]
    assert "palabra_reddit" not in redist_terms
    assert "par_sintetico_mex" in redist_terms


def test_human_review_of_source_requires_pseudonym(provenance_env):
    """La revisión y aprobación de fuentes exige identificador seudónimo 'rev_XXXX'."""
    db = provenance_env["db"]

    register_data_source(
        db=db,
        source_id="src_new_feed",
        name="Nuevo Feed",
        canonical_origin="newfeed.mx",
        source_type="discovery_feed",
        license_ref="terms_v1",
        allowed_uses=["discovery"],
        permission_status="quarantine",
    )

    # Revisor sin formato rev_ debe fallar
    with pytest.raises(ValueError, match="rev_XXXX"):
        review_data_source(db, "src_new_feed", "approved", reviewer="admin_real_name")

    # Revisor con formato válido
    source = review_data_source(db, "src_new_feed", "approved", reviewer="rev_luis")
    assert source is not None
    assert source.permission_status == "approved"
    assert source.reviewed_by == "rev_luis"


def test_admin_api_endpoints_for_provenance(provenance_env):
    """Prueba los endpoints HTTP /admin/api/sources y /admin/api/dataset/export."""
    client = provenance_env["client"]
    admin_key = provenance_env["admin_key"]
    headers = {"X-API-Key": admin_key}

    # 1. Listar fuentes
    res_list = client.get("/admin/api/sources", headers=headers)
    assert res_list.status_code == 200
    sources = res_list.json()["data"]
    assert len(sources) >= 5
    assert any(s["id"] == "src_reddit_discovery" for s in sources)

    # 2. Registrar nueva fuente vía API
    res_reg = client.post(
        "/admin/api/sources",
        headers=headers,
        json={
            "id": "src_api_registered",
            "name": "API Source",
            "canonical_origin": "api.test",
            "source_type": "discovery_feed",
            "license_or_permission_ref": "test_ref",
            "allowed_uses": ["discovery"],
            "permission_status": "quarantine",
        },
    )
    assert res_reg.status_code == 200
    assert res_reg.json()["data"]["permission_status"] == "quarantine"

    # 3. Export vía API
    res_export = client.get("/admin/api/dataset/export?target_use=training", headers=headers)
    assert res_export.status_code == 200
    manifest = res_export.json()["data"]
    assert manifest["target_use"] == "training"
    assert "exclusions_breakdown" in manifest
