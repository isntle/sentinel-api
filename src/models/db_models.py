from sqlalchemy import Column, String, Integer, Float, Boolean, ForeignKey, Table, Text
from sqlalchemy.orm import relationship
from src.database import Base

# Tabla intermedia para la relación de Usuarios y Sesiones
user_sessions = Table(
    'user_sessions',
    Base.metadata,
    Column('user_id', String, ForeignKey('users.id', ondelete="CASCADE"), primary_key=True),
    Column('session_id', String, ForeignKey('sessions.id', ondelete="CASCADE"), primary_key=True)
)

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    profile = Column(String, nullable=True)

    # Relaciones
    sessions = relationship("Session", secondary=user_sessions, back_populates="users")
    messages = relationship("Message", back_populates="user")

class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    created_at = Column(Integer, nullable=False)
    last_activity = Column(Integer, nullable=False)
    purge_at = Column(Integer, nullable=False)
    api_key_hash = Column(String, nullable=True, index=True)

    # Relaciones
    users = relationship("User", secondary=user_sessions, back_populates="sessions")
    messages = relationship("Message", back_populates="session")

class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    content = Column(String, nullable=False)
    timestamp = Column(Integer, nullable=False)

    # Relaciones para navegar fácilmente entre objetos
    user = relationship("User", back_populates="messages")
    session = relationship("Session", back_populates="messages")

class HotTerm(Base):
    __tablename__ = "hot_terms"

    id = Column(String, primary_key=True)          # UUID generado por la API
    term = Column(String, nullable=False)           # el término nuevo
    category = Column(String, nullable=False)       # reclutamiento, grooming, etc.
    weight = Column(Float, nullable=False)          # peso en el scoring (igual que dataset)
    initial_weight = Column(Float, nullable=True)   # piso relativo para calibración
    variants = Column(String, nullable=True)        # variantes separadas por coma
    source = Column(String, nullable=True)          # de dónde vino el término (etiqueta legible)
    source_id = Column(String, nullable=True, index=True) # ID formal del DataSource
    canonical_origin = Column(String, nullable=True, index=True) # Origen canónico (ej. dominio/organización)
    content_hash = Column(String, nullable=True, index=True)     # Hash de contenido para deduplicación
    approved = Column(Boolean, default=False)       # True = ya validado, se sirve al SDK
    staged = Column(Boolean, default=False)         # True = aprobado por IA, esperando revisión
    reviewed = Column(Boolean, default=False)       # True = humano aprobó; aún no publicado
    created_at = Column(Integer, nullable=False)    # Unix timestamp

class DatasetVersion(Base):
    __tablename__ = "dataset_versions"

    version = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(Integer, nullable=False)
    description = Column(String, nullable=True)
    terms_snapshot = Column(String, nullable=False) # JSON list of hot terms in this version
    status = Column(String, nullable=False, default="published")
    base_version = Column(Integer, nullable=True)
    calibration_run_id = Column(String, nullable=True, unique=True, index=True)
    audit_json = Column(String, nullable=True)

class RejectedTerm(Base):
    __tablename__ = "rejected_terms"

    id = Column(String, primary_key=True)
    term = Column(String, nullable=False)
    source = Column(String, nullable=True)
    reasoning = Column(String, nullable=True)
    rejected_at = Column(Integer, nullable=False)

class DataSource(Base):
    """Registro formal de procedencia, permisos y derechos de uso de datos."""
    __tablename__ = "data_sources"

    id = Column(String, primary_key=True)                      # Identificador único (ej: src_reddit_narco)
    name = Column(String, nullable=False)                      # Nombre descriptivo
    canonical_origin = Column(String, nullable=False, index=True) # Dominio o entidad editorial canónica
    source_type = Column(String, nullable=False)               # expert_annotation, synthetic_scenario, discovery_feed, legacy_seed, public_dataset
    permission_status = Column(String, nullable=False, default="quarantine") # approved, quarantine, unknown, revoked
    allowed_uses = Column(String, nullable=False, default="discovery")      # CSV: discovery,training,evaluation,redistribution
    license_or_permission_ref = Column(String, nullable=False) # Referencia legal o acuerdo
    created_at = Column(Integer, nullable=False)
    reviewed_by = Column(String, nullable=True)                # Revisor seudónimo (ej: rev_luis)
    reviewed_at = Column(Integer, nullable=True)
    parent_source_id = Column(String, nullable=True)           # Para linaje de datasets derivados

class CandidateSighting(Base):
    __tablename__ = "candidate_sightings"

    id = Column(String, primary_key=True)
    term = Column(String, nullable=False)
    source = Column(String, nullable=False)
    source_id = Column(String, nullable=True, index=True)
    canonical_origin = Column(String, nullable=True, index=True)
    content_hash = Column(String, nullable=True, index=True)
    context = Column(String, nullable=True)
    seen_at = Column(Integer, nullable=False)

class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(String, primary_key=True)
    session_id = Column(String, nullable=False)
    verdict_original = Column(String, nullable=False)  # JSON string with risk, score, terms
    feedback_type = Column(String, nullable=False)     # 'false_positive', 'false_negative', 'confirmed'
    comment = Column(String, nullable=True)
    reported_by = Column(String, nullable=False)
    created_at = Column(Integer, nullable=False)
    # Procedencia derivada de autenticación; nullable solo para filas legacy.
    api_key_hash = Column(String, nullable=True, index=True)
    dataset_version = Column(Integer, nullable=True, index=True)
    term_ids = Column(Text, nullable=True)
    feedback_fingerprint = Column(String, nullable=True, unique=True, index=True)

class ApiKey(Base):
    __tablename__ = "api_keys"

    key_hash = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    scope = Column(String, nullable=False)          # 'client' | 'admin'
    created_at = Column(Integer, nullable=False)
    revoked_at = Column(Integer, nullable=True)
    last_used_at = Column(Integer, nullable=True)

class ScraperRun(Base):
    __tablename__ = "scraper_runs"

    id = Column(String, primary_key=True)
    started_at = Column(Integer, nullable=False)
    finished_at = Column(Integer, nullable=True)
    status = Column(String, nullable=False) # 'running', 'success', 'failed'
    results = Column(String, nullable=True) # JSON string
    error = Column(String, nullable=True)

class ActorSighting(Base):
    """
    Registro cross-sesión para detectar reclutamiento organizado (un actor → N
    víctimas). PRIVACIDAD POR DISEÑO: nunca se guarda contenido de mensajes ni
    identificadores en claro. Solo hashes (user_id y session con sal del
    servidor) y agregados. Sujeto a purga por retención como los mensajes.
    """
    __tablename__ = "actor_sightings"

    id = Column(String, primary_key=True)
    actor_hash = Column(String, nullable=False, index=True)   # SHA-256(salt + aggressor user_id)
    session_hash = Column(String, nullable=False)              # SHA-256(salt + session_id)
    script_fp = Column(String, nullable=True, index=True)      # huella del guion (n-gramas hasheados)
    risk = Column(String, nullable=True)                       # veredicto de la sesión
    categories = Column(String, nullable=True)                 # categorías (CSV), sin contenido
    created_at = Column(Integer, nullable=False, index=True)
    api_key_hash = Column(String, nullable=True, index=True)


class AnalysisRecord(Base):
    """Snapshot temporal de una escalación, sujeto a la retención de 7 días."""
    __tablename__ = "analysis_records"

    id = Column(String, primary_key=True)
    session_id = Column(String, nullable=False, index=True)
    api_key_hash = Column(String, nullable=False, index=True)
    risk = Column(String, nullable=False, index=True)
    analysis_payload = Column(Text, nullable=False)
    llm_verdict = Column(Text, nullable=False)
    dataset_versions = Column(Text, nullable=False)
    created_at = Column(Integer, nullable=False, index=True)
    purge_at = Column(Integer, nullable=False, index=True)


class EvidencePackage(Base):
    """Instantánea inmutable creada por legal hold; no participa en la purga normal."""
    __tablename__ = "evidence_packages"

    id = Column(String, primary_key=True)
    # Sin FK deliberadamente: purgar AnalysisRecord no debe borrar ni bloquear
    # una evidencia que el cliente solicitó conservar.
    analysis_record_id = Column(String, nullable=False, unique=True, index=True)
    session_id = Column(String, nullable=False, index=True)
    api_key_hash = Column(String, nullable=False, index=True)
    canonical_payload = Column(Text, nullable=False)
    content_hash = Column(String, nullable=False)
    created_at = Column(Integer, nullable=False, index=True)


class TelemetrySnapshot(Base):
    """Contadores agregados; nunca contiene mensajes ni IDs de usuario/sesión."""
    __tablename__ = "telemetry_snapshots"

    id = Column(String, primary_key=True)
    api_key_hash = Column(String, nullable=False, index=True)
    created_at = Column(Integer, nullable=False, index=True)
    purge_at = Column(Integer, nullable=False, index=True)
    total_analyses = Column(Integer, nullable=False)
    low_count = Column(Integer, nullable=False)
    medium_count = Column(Integer, nullable=False)
    high_count = Column(Integer, nullable=False)
    critical_count = Column(Integer, nullable=False)
    v3_term_counts = Column(Text, nullable=False)
    api_escalations = Column(Integer, nullable=False)
    local_resolutions = Column(Integer, nullable=False)
    cached_api_verdicts = Column(Integer, nullable=False)
    shadow_agreements = Column(Integer, nullable=False)
    shadow_disagreements = Column(Integer, nullable=False)
    shadow_model_counts = Column(Text, nullable=False, default="{}")
    intervention_observed_count = Column(Integer, nullable=False, default=0)
    allow_count = Column(Integer, nullable=False, default=0)
    silent_observe_count = Column(Integer, nullable=False, default=0)
    soft_warn_count = Column(Integer, nullable=False, default=0)
    hard_block_count = Column(Integer, nullable=False, default=0)
    protective_action_counts = Column(Text, nullable=False, default="{}")


class ShadowModelArtifact(Base):
    """Modelo candidato validado; publicar crea una release monotónica separada."""
    __tablename__ = "shadow_model_artifacts"

    model_id = Column(String, primary_key=True)
    feature_schema_version = Column(Integer, nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(Integer, nullable=False, index=True)
    staged = Column(Boolean, nullable=False, default=True)


class ShadowModelRelease(Base):
    """Historial append-only. Rollback crea otra release; nunca baja versión."""
    __tablename__ = "shadow_model_releases"

    version = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(
        String,
        ForeignKey("shadow_model_artifacts.model_id"),
        nullable=False,
        index=True,
    )
    created_at = Column(Integer, nullable=False, index=True)
    action = Column(String, nullable=False)  # publish | rollback


class ActiveLearningQueueItem(Base):
    """
    Cola de aprendizaje activo y revisión humana (S17).
    Gobernanza:
    1. Distingue muestreo activo (incertidumbre/desacuerdo) de muestreo aleatorio uniforme.
    2. Estados estrictos: pending -> reviewed -> adjudicated -> eligible.
    3. Cero auto-aprobación o re-entrenamiento automático sin adjudicación humana explícita.
    """
    __tablename__ = "active_learning_queue"

    id = Column(String, primary_key=True)
    session_id = Column(String, nullable=False, index=True)
    api_key_hash = Column(String, nullable=False, index=True)
    family_id = Column(String, nullable=True, index=True)
    sampling_strategy = Column(String, nullable=False, index=True)  # uncertainty | disagreement | random_baseline | feedback
    inclusion_probability = Column(Float, nullable=False, default=1.0)
    features_json = Column(Text, nullable=True)                     # Solo features numéricas / metadatos, sin texto de mensajes
    primary_verdict = Column(String, nullable=True)
    shadow_probability = Column(Float, nullable=True)
    uncertainty_score = Column(Float, nullable=True)
    disagreement = Column(Boolean, nullable=False, default=False)
    status = Column(String, nullable=False, default="pending", index=True)  # pending | reviewed | adjudicated | eligible | rejected
    blind_review = Column(Boolean, nullable=False, default=True)
    first_reviewer_id = Column(String, nullable=True)               # Revisor seudónimo rev_XXXX
    first_verdict = Column(String, nullable=True)                   # BENIGN | RISK | INSUFFICIENT_CONTEXT
    second_reviewer_id = Column(String, nullable=True)              # Revisor seudónimo rev_YYYY
    second_verdict = Column(String, nullable=True)
    adjudicated_verdict = Column(String, nullable=True)
    adjudicated_by = Column(String, nullable=True)
    fingerprint = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(Integer, nullable=False, index=True)
    reviewed_at = Column(Integer, nullable=True)
    retention_purge_at = Column(Integer, nullable=False, index=True)

