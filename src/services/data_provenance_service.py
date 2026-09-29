"""
Servicio de Procedencia, Permisos y Gobernanza de Datos (S08).

Garantiza la trazabilidad canónica de cada término, avistamiento y fragmento
de entrenamiento:
1. Distingue formalmente entre derechos de DESCUBRIMIENTO, ENTRENAMIENTO,
   EVALUACIÓN y REDISTRIBUCIÓN.
2. Fuentes nuevas entran en CUARENTENA hasta revisión humana explícita.
3. Excluye estrictamente registros heredados sin trazabilidad o con estatus 'unknown'
   de cualquier exportación orientada a entrenamiento o redistribución.
4. Deduplica por hash de contenido y origen canónico.
"""

import hashlib
import re
import time
from sqlalchemy.orm import Session
from src.models.db_models import DataSource, HotTerm, CandidateSighting

VALID_USES = {"discovery", "training", "evaluation", "redistribution"}
VALID_STATUSES = {"approved", "quarantine", "unknown", "revoked"}
VALID_SOURCE_TYPES = {
    "expert_annotation",
    "synthetic_scenario",
    "discovery_feed",
    "legacy_seed",
    "public_dataset",
    "academic_paper",
}

CANONICAL_SOURCES = [
    {
        "id": "src_legacy_seed",
        "name": "Corpus Semilla Histórico Sentinel",
        "canonical_origin": "sentinel_legacy_corpus",
        "source_type": "legacy_seed",
        "permission_status": "unknown",
        "allowed_uses": "discovery",
        "license_or_permission_ref": "unknown_historical_lineage",
    },
    {
        "id": "src_reddit_discovery",
        "name": "Reddit Feeds de Jerga y Discusión Pública",
        "canonical_origin": "reddit.com",
        "source_type": "discovery_feed",
        "permission_status": "approved",
        "allowed_uses": "discovery",
        "license_or_permission_ref": "reddit_data_api_terms_discovery_only",
    },
    {
        "id": "src_borderlandbeat_discovery",
        "name": "Borderland Beat Public News Archive",
        "canonical_origin": "borderlandbeat.com",
        "source_type": "discovery_feed",
        "permission_status": "approved",
        "allowed_uses": "discovery",
        "license_or_permission_ref": "public_web_reporting_discovery_only",
    },
    {
        "id": "src_rss_mexico_news",
        "name": "Monitoreo RSS Noticias de Seguridad México",
        "canonical_origin": "mexican_news_rss",
        "source_type": "discovery_feed",
        "permission_status": "approved",
        "allowed_uses": "discovery",
        "license_or_permission_ref": "rss_fair_use_headline_monitoring",
    },
    {
        "id": "src_expert_curated_mexican_rubric",
        "name": "Panel de Expertos y Rúbrica Mexicana Sentinel v1",
        "canonical_origin": "sentinel_expert_panel",
        "source_type": "expert_annotation",
        "permission_status": "approved",
        "allowed_uses": "discovery,training,evaluation",
        "license_or_permission_ref": "sentinel_mexican_rubric_v1_consent",
    },
    {
        "id": "src_synthetic_contrastive_mexican",
        "name": "Escenarios Contrastivos Sintéticos Mexicanos (CC-BY 4.0)",
        "canonical_origin": "sentinel_synthetic_pipeline",
        "source_type": "synthetic_scenario",
        "permission_status": "approved",
        "allowed_uses": "discovery,training,evaluation,redistribution",
        "license_or_permission_ref": "cc_by_4_0_synthetic_contrastive",
    },
]


def calculate_content_hash(text: str | None) -> str:
    """Calcula hash determinista de contenido normalizado para deduplicación."""
    if not text:
        return "empty_content_hash"
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def resolve_canonical_origin(source_str: str | None) -> str:
    """Deriva el origen canónico o dominio a partir de la etiqueta de la fuente."""
    if not source_str:
        return "unknown_origin"
    s = source_str.lower()
    if "reddit" in s:
        return "reddit.com"
    if "borderland" in s:
        return "borderlandbeat.com"
    if "riodoce" in s or "río doce" in s:
        return "riodoce.mx"
    if "zeta" in s:
        return "zetatijuana.com"
    if "proceso" in s:
        return "proceso.com.mx"
    if "silla rota" in s:
        return "lasillarota.com"
    if "youtube" in s:
        return "youtube.com"
    if "genius" in s or "corrido" in s:
        return "genius.com"
    if "expert" in s or "rubric" in s:
        return "sentinel_expert_panel"
    if "synthetic" in s or "contrast" in s:
        return "sentinel_synthetic_pipeline"
    if "seed" in s or "legacy" in s:
        return "sentinel_legacy_corpus"
    return re.sub(r"[^a-z0-9_.-]", "_", s.strip())[:64]


def ensure_canonical_data_sources(db: Session) -> None:
    """Garantiza la presencia de las fuentes canónicas en la base de datos."""
    now = int(time.time())
    for src in CANONICAL_SOURCES:
        existing = db.query(DataSource).filter(DataSource.id == src["id"]).first()
        if not existing:
            db.add(
                DataSource(
                    id=src["id"],
                    name=src["name"],
                    canonical_origin=src["canonical_origin"],
                    source_type=src["source_type"],
                    permission_status=src["permission_status"],
                    allowed_uses=src["allowed_uses"],
                    license_or_permission_ref=src["license_or_permission_ref"],
                    created_at=now,
                    reviewed_by="rev_system_init",
                    reviewed_at=now,
                )
            )
    db.commit()


def register_data_source(
    db: Session,
    source_id: str,
    name: str,
    canonical_origin: str,
    source_type: str,
    license_ref: str,
    allowed_uses: list[str],
    permission_status: str = "quarantine",
    reviewer: str | None = None,
) -> DataSource:
    """Registra o actualiza una fuente de datos con cuarentena por defecto."""
    if source_type not in VALID_SOURCE_TYPES:
        raise ValueError(f"Invalid source_type: {source_type}. Valid: {VALID_SOURCE_TYPES}")
    if permission_status not in VALID_STATUSES:
        raise ValueError(f"Invalid permission_status: {permission_status}. Valid: {VALID_STATUSES}")
    for u in allowed_uses:
        if u not in VALID_USES:
            raise ValueError(f"Invalid use: {u}. Valid: {VALID_USES}")

    now = int(time.time())
    existing = db.query(DataSource).filter(DataSource.id == source_id).first()
    if existing:
        existing.name = name
        existing.canonical_origin = canonical_origin
        existing.source_type = source_type
        existing.license_or_permission_ref = license_ref
        existing.allowed_uses = ",".join(allowed_uses)
        existing.permission_status = permission_status
        if reviewer:
            existing.reviewed_by = reviewer
            existing.reviewed_at = now
        db.commit()
        db.refresh(existing)
        return existing

    new_source = DataSource(
        id=source_id,
        name=name,
        canonical_origin=canonical_origin,
        source_type=source_type,
        permission_status=permission_status,
        allowed_uses=",".join(allowed_uses),
        license_or_permission_ref=license_ref,
        created_at=now,
        reviewed_by=reviewer,
        reviewed_at=now if reviewer else None,
    )
    db.add(new_source)
    db.commit()
    db.refresh(new_source)
    return new_source


def review_data_source(
    db: Session,
    source_id: str,
    permission_status: str,
    reviewer: str,
    allowed_uses: list[str] | None = None,
) -> DataSource | None:
    """Aprobación, pase a cuarentena o revocación humana de una fuente."""
    if permission_status not in VALID_STATUSES:
        raise ValueError(f"Invalid permission_status: {permission_status}")
    if not reviewer or not reviewer.startswith("rev_"):
        raise ValueError("Human reviewer must have a pseudonymous ID format 'rev_XXXX'")

    source = db.query(DataSource).filter(DataSource.id == source_id).first()
    if not source:
        return None

    now = int(time.time())
    source.permission_status = permission_status
    source.reviewed_by = reviewer
    source.reviewed_at = now
    if allowed_uses is not None:
        for u in allowed_uses:
            if u not in VALID_USES:
                raise ValueError(f"Invalid use: {u}")
        source.allowed_uses = ",".join(allowed_uses)

    db.commit()
    db.refresh(source)
    return source


def export_dataset_by_usage(
    db: Session,
    target_use: str,
    category: str | None = None,
) -> dict:
    """
    Exporta datos filtrados estrictamente por permisos del origen canónico.

    - target_use: 'discovery' | 'training' | 'evaluation' | 'redistribution'
    - Bloquea fuentes desconocidas, en cuarentena o revocadas cuando se exporta
      para entrenamiento o redistribución.
    """
    if target_use not in VALID_USES:
        raise ValueError(f"Invalid target_use '{target_use}'. Must be one of: {sorted(VALID_USES)}")

    ensure_canonical_data_sources(db)
    sources_by_id = {s.id: s for s in db.query(DataSource).all()}

    query = db.query(HotTerm)
    if category:
        query = query.filter(HotTerm.category == category)
    terms = query.all()

    exported_items = []
    excluded_breakdown = {
        "unauthorized_usage_rights": 0,
        "quarantined_source": 0,
        "unknown_permissions": 0,
        "revoked_source": 0,
        "unreviewed_term": 0,
    }

    for t in terms:
        # 1. Resolver fuente formal
        src_id = t.source_id
        source_obj = sources_by_id.get(src_id) if src_id else None

        if not source_obj:
            # Intentar resolver por origen canónico o asignar a legacy desconocido
            canon_origin = t.canonical_origin or resolve_canonical_origin(t.source)
            # Buscar fuente por canonical_origin
            for candidate_src in sources_by_id.values():
                if candidate_src.canonical_origin == canon_origin:
                    source_obj = candidate_src
                    break
            if not source_obj:
                source_obj = sources_by_id.get("src_legacy_seed")

        # 2. Verificar estatus de permisos de la fuente
        status = source_obj.permission_status if source_obj else "unknown"
        allowed = set(source_obj.allowed_uses.split(",")) if source_obj else set()

        if status == "unknown":
            excluded_breakdown["unknown_permissions"] += 1
            continue

        if status == "quarantine":
            excluded_breakdown["quarantined_source"] += 1
            continue

        if status == "revoked":
            excluded_breakdown["revoked_source"] += 1
            continue

        if status != "approved":
            excluded_breakdown["unknown_permissions"] += 1
            continue

        # 3. Verificar que el uso solicitado esté formalmente autorizado
        if target_use not in allowed:
            excluded_breakdown["unauthorized_usage_rights"] += 1
            continue

        # 4. Para entrenamiento, requerir que el término haya sido revisado o aprobado
        if target_use in {"training", "redistribution"} and not (t.approved or t.reviewed):
            excluded_breakdown["unreviewed_term"] += 1
            continue

        exported_items.append({
            "id": t.id,
            "term": t.term,
            "category": t.category,
            "weight": t.weight,
            "variants": t.variants.split(",") if t.variants else [],
            "source_id": source_obj.id,
            "canonical_origin": source_obj.canonical_origin,
            "source_type": source_obj.source_type,
            "license_ref": source_obj.license_or_permission_ref,
            "allowed_uses": list(allowed),
            "rights_status": status,
            "content_hash": t.content_hash or calculate_content_hash(t.term),
            "created_at": t.created_at,
        })

    return {
        "target_use": target_use,
        "manifest_version": "1.0",
        "total_terms_examined": len(terms),
        "exported_count": len(exported_items),
        "excluded_count": sum(excluded_breakdown.values()),
        "exclusions_breakdown": excluded_breakdown,
        "items": exported_items,
    }
