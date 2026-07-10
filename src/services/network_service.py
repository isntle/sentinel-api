"""
Señales de red — detección de reclutamiento ORGANIZADO cruzando sesiones.

El SDK detecta la asimetría DENTRO de una sesión (un actor concentra tácticas).
Este servicio es el complemento servidor-side: cruza sesiones para ver el patrón
que ninguna sesión aislada revela — un reclutador contactando a N menores con el
mismo guion. "Este usuario ya fue zona gris con otros 4 menores esta semana" es
una señal más fuerte que cualquier término.

PRIVACIDAD POR DISEÑO:
- Nunca se persiste contenido de mensajes ni user_id/session_id en claro.
- Los identificadores se hashean con SHA-256 + una sal secreta del servidor.
- La huella del guion es un hash de n-gramas normalizados, no el texto.
- Los avistamientos se purgan por retención igual que los mensajes.
"""
import hashlib
import re
import uuid
import time
from sqlalchemy.orm import Session
from src.models.db_models import ActorSighting
from src.config.settings import ACTOR_HASH_SALT

# Ventanas y umbrales de las reglas de red.
RECIDIVISM_MIN_SESSIONS = 2      # mismo actor en ≥2 sesiones distintas
SPRAY_WINDOW_SECONDS = 24 * 3600 # ráfaga: muchas sesiones nuevas en 24h
SPRAY_MIN_SESSIONS = 3
SCRIPT_REUSE_MIN_SESSIONS = 2    # mismo guion en ≥2 sesiones (distintas víctimas)


def _hash(value: str) -> str:
    return hashlib.sha256(f"{ACTOR_HASH_SALT}:{value}".encode()).hexdigest()


def _script_fingerprint(texts: list[str]) -> str | None:
    """
    Huella estable del 'guion' del actor: normaliza el texto, toma los primeros
    ~120 caracteres (la apertura, que es lo que se copia-pega entre víctimas) y
    lo hashea. No se guarda el texto — solo su hash. Dos aperturas idénticas
    producen la misma huella aunque cambien nombres/detalles al final.
    """
    joined = " ".join(texts).lower()
    normalized = re.sub(r"[^a-záéíóúñ0-9 ]", "", joined)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if len(normalized) < 12:
        return None
    opening = normalized[:120]
    return hashlib.sha256(opening.encode()).hexdigest()[:32]


def record_and_score(
    db: Session,
    aggressor_user_id: str | None,
    session_id: str,
    aggressor_texts: list[str],
    risk: str,
    categories: list[str],
) -> dict:
    """
    Registra el avistamiento del actor (si hay agresor identificado) y devuelve
    el riesgo de red agregado para ese actor. Si no hay agresor, devuelve un
    resultado neutro sin persistir nada.
    """
    if not aggressor_user_id:
        return {"actor_risk": "NONE", "signals": [], "distinct_sessions": 0}

    actor_hash = _hash(aggressor_user_id)
    session_hash = _hash(session_id)
    script_fp = _script_fingerprint(aggressor_texts)
    now = int(time.time())

    # Persistir el avistamiento (solo hashes y agregados).
    db.add(ActorSighting(
        id=str(uuid.uuid4()),
        actor_hash=actor_hash,
        session_hash=session_hash,
        script_fp=script_fp,
        risk=risk,
        categories=",".join(categories) if categories else None,
        created_at=now,
    ))
    db.commit()

    return _score_actor(db, actor_hash, script_fp, now)


def _score_actor(db: Session, actor_hash: str, script_fp: str | None, now: int) -> dict:
    sightings = db.query(ActorSighting).filter(ActorSighting.actor_hash == actor_hash).all()
    distinct_sessions = {s.session_hash for s in sightings}
    signals: list[str] = []

    # Reincidencia: el mismo actor escaló en varias sesiones distintas.
    if len(distinct_sessions) >= RECIDIVISM_MIN_SESSIONS:
        signals.append("RECIDIVISM")

    # Ráfaga (spray): muchas sesiones nuevas del actor en poco tiempo.
    recent = {s.session_hash for s in sightings if now - s.created_at <= SPRAY_WINDOW_SECONDS}
    if len(recent) >= SPRAY_MIN_SESSIONS:
        signals.append("SPRAY")

    # Guion reutilizado: la misma apertura contra víctimas (sesiones) distintas.
    if script_fp:
        same_script = db.query(ActorSighting).filter(ActorSighting.script_fp == script_fp).all()
        script_sessions = {s.session_hash for s in same_script}
        if len(script_sessions) >= SCRIPT_REUSE_MIN_SESSIONS:
            signals.append("SCRIPT_REUSE")

    # Riesgo de red: cualquier reutilización de guion o ráfaga es CRÍTICO
    # (reclutamiento sistemático); la sola reincidencia es HIGH.
    if "SCRIPT_REUSE" in signals or "SPRAY" in signals:
        actor_risk = "CRITICAL"
    elif "RECIDIVISM" in signals:
        actor_risk = "HIGH"
    else:
        actor_risk = "NONE"

    return {
        "actor_risk": actor_risk,
        "signals": signals,
        "distinct_sessions": len(distinct_sessions),
    }


def top_risky_actors(db: Session, limit: int = 50) -> list[dict]:
    """Vista administrativa: actores con más sesiones distintas (posible red)."""
    sightings = db.query(ActorSighting).all()
    by_actor: dict[str, dict] = {}
    for s in sightings:
        a = by_actor.setdefault(s.actor_hash, {"sessions": set(), "scripts": set(), "last_seen": 0})
        a["sessions"].add(s.session_hash)
        if s.script_fp:
            a["scripts"].add(s.script_fp)
        a["last_seen"] = max(a["last_seen"], s.created_at)

    rows = [
        {
            "actor_hash": actor_hash[:12] + "…",  # prefijo, para no exponer el hash completo
            "distinct_sessions": len(a["sessions"]),
            "distinct_scripts": len(a["scripts"]),
            "last_seen": a["last_seen"],
        }
        for actor_hash, a in by_actor.items()
        if len(a["sessions"]) >= RECIDIVISM_MIN_SESSIONS
    ]
    rows.sort(key=lambda r: r["distinct_sessions"], reverse=True)
    return rows[:limit]


def purge_expired_sightings(db: Session, retention_days: int = 30) -> int:
    """Purga avistamientos más viejos que la retención (minimización de datos)."""
    cutoff = int(time.time()) - retention_days * 24 * 3600
    deleted = db.query(ActorSighting).filter(ActorSighting.created_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return deleted
