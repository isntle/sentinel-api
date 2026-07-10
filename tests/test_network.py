import sys
import os
import time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from src.database import SessionLocal, Base, engine
from src.models.db_models import ActorSighting
from src.services.network_service import (
    record_and_score,
    top_risky_actors,
    purge_expired_sightings,
    _hash,
    _script_fingerprint,
)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    # Limpiar avistamientos de corridas previas para aislar el test.
    session.query(ActorSighting).delete()
    session.commit()
    yield session
    session.query(ActorSighting).delete()
    session.commit()
    session.close()


GUION = ["oye te vi por aqui, tengo un jale para ti, se gana bien, manda tu ubicacion"]


def test_primer_contacto_sin_riesgo_de_red(db):
    r = record_and_score(db, "narco-x", "s-1", GUION, "CAPTACION", ["reclutamiento"])
    assert r["actor_risk"] == "NONE"
    assert r["distinct_sessions"] == 1


def test_reincidencia_y_guion_reutilizado_es_critico(db):
    record_and_score(db, "narco-x", "s-1", GUION, "CAPTACION", ["reclutamiento"])
    r = record_and_score(db, "narco-x", "s-2", GUION, "CAPTACION", ["reclutamiento"])
    assert r["actor_risk"] == "CRITICAL"
    assert "RECIDIVISM" in r["signals"]
    assert "SCRIPT_REUSE" in r["signals"]
    assert r["distinct_sessions"] == 2


def test_spray_con_tres_sesiones(db):
    for menor in ["a", "b", "c"]:
        r = record_and_score(db, "narco-x", f"s-{menor}", GUION, "CAPTACION", ["reclutamiento"])
    assert "SPRAY" in r["signals"]


def test_actor_sin_agresor_no_persiste_nada(db):
    r = record_and_score(db, None, "s-1", GUION, "NINGUNA", [])
    assert r["actor_risk"] == "NONE"
    assert db.query(ActorSighting).count() == 0


def test_privacidad_no_se_guarda_contenido_ni_ids_en_claro(db):
    record_and_score(db, "narco-x", "sesion-secreta", GUION, "CAPTACION", ["reclutamiento"])
    row = db.query(ActorSighting).first()
    # El user_id y session_id en claro NO deben aparecer en ninguna columna.
    assert "narco-x" not in (row.actor_hash or "")
    assert "sesion-secreta" not in (row.session_hash or "")
    # El texto del guion tampoco se guarda; solo su huella hasheada.
    assert GUION[0] not in (row.script_fp or "")
    assert row.actor_hash == _hash("narco-x")


def test_dos_actores_distintos_no_se_cruzan(db):
    record_and_score(db, "narco-x", "s-1", GUION, "CAPTACION", ["reclutamiento"])
    r = record_and_score(db, "otro-actor", "s-2", ["hola amigo"], "NINGUNA", ["señal_debil"])
    assert r["actor_risk"] == "NONE"  # actor distinto, sin historial


def test_purga_elimina_avistamientos_viejos(db):
    record_and_score(db, "narco-x", "s-1", GUION, "CAPTACION", ["reclutamiento"])
    # Envejecer artificialmente el avistamiento.
    row = db.query(ActorSighting).first()
    row.created_at = int(time.time()) - 40 * 24 * 3600
    db.commit()
    deleted = purge_expired_sightings(db, retention_days=30)
    assert deleted == 1


def test_huella_de_guion_detecta_reuso_verbatim(db):
    # Guion idéntico → misma huella (detecta copy-paste entre víctimas).
    # Opening claramente > 120 chars para probar el truncado.
    guion = ("hola te vi por aqui y me caiste rebien la verdad, mira tengo un trabajo bien "
             "facil para que ganes buena lana rapido sin que nadie de tu casa se entere de nada")
    fp1 = _script_fingerprint([guion])
    fp2 = _script_fingerprint([guion])
    assert fp1 == fp2

    # La huella trunca a 120 chars: el ruido MÁS ALLÁ de la apertura no cambia
    # la huella (personalización al final de un guion largo).
    fp_suffix = _script_fingerprint([guion + " saludos y bendiciones Juan Perez"])
    assert fp_suffix == fp1

    # Guion distinto → huella distinta.
    fp3 = _script_fingerprint(["conversacion totalmente distinta sobre la tarea de la escuela"])
    assert fp3 != fp1

    # Texto demasiado corto → sin huella (no se cruza).
    assert _script_fingerprint(["hola"]) is None
