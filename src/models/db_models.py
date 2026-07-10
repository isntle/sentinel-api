from sqlalchemy import Column, String, Integer, Float, Boolean, ForeignKey, Table
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
    variants = Column(String, nullable=True)        # variantes separadas por coma
    source = Column(String, nullable=True)          # de dónde vino el término
    approved = Column(Boolean, default=False)       # True = ya validado, se sirve al SDK
    staged = Column(Boolean, default=False)         # True = aprobado por IA, esperando revisión
    created_at = Column(Integer, nullable=False)    # Unix timestamp

class DatasetVersion(Base):
    __tablename__ = "dataset_versions"

    version = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(Integer, nullable=False)
    description = Column(String, nullable=True)
    terms_snapshot = Column(String, nullable=False) # JSON list of hot terms in this version

class RejectedTerm(Base):
    __tablename__ = "rejected_terms"

    id = Column(String, primary_key=True)
    term = Column(String, nullable=False)
    source = Column(String, nullable=True)
    reasoning = Column(String, nullable=True)
    rejected_at = Column(Integer, nullable=False)

class CandidateSighting(Base):
    __tablename__ = "candidate_sightings"

    id = Column(String, primary_key=True)
    term = Column(String, nullable=False)
    source = Column(String, nullable=False)
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
