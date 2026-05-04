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
    created_at = Column(Integer, nullable=False)    # Unix timestamp
