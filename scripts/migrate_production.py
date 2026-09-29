"""
Migración de producción para Railway.

Este proyecto no usa Alembic — las tablas nuevas del modelo (DatasetVersion,
RejectedTerm, CandidateSighting, Feedback, ApiKey, ScraperRun, AnalysisRecord,
EvidencePackage, TelemetrySnapshot) las crea solo
`Base.metadata.create_all()` en el arranque de main.py, porque SQLAlchemy sí
sabe crear tablas que no existen. Lo que NO hace solo es alterar una tabla que
ya existe en producción para agregarle una columna nueva — por eso hot_terms
necesita este script: la columna `staged` es nueva y sin ella el deploy
truena en cuanto algo intente leer o escribir ese campo.

Uso:
    DATABASE_URL="postgresql://..." python scripts/migrate_production.py

Si DATABASE_URL no está seteada, usa el sqlite local (mismo default que
src/database.py) — útil para probar el script antes de correrlo en Railway.

Qué hace, en orden:
  1. Crea todas las tablas del modelo que falten (no toca las que ya existen).
  2. Agrega la columna `staged` a `hot_terms` si no existe.
  3. Agrega columnas de procedencia, revisión y calibración si faltan.
  4. Si no hay ninguna fila en `api_keys`, crea una llave admin y una client,
     e IMPRIME LAS LLAVES EN CLARO UNA SOLA VEZ (no quedan en ningún lado más
     que en la terminal — guárdalas ahora).

Es idempotente: se puede correr varias veces sin duplicar nada ni romper una
base que ya está migrada.
"""
import os
import secrets
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text

from src.database import engine, SessionLocal, Base
from src.models import db_models
from src.core.security import hash_api_key


def create_missing_tables():
    print("1. Creando tablas nuevas del modelo (si faltan)...")
    Base.metadata.create_all(bind=engine)
    print("   OK.")


def add_staged_column_if_missing():
    print("2. Revisando columna 'staged' en hot_terms...")
    inspector = inspect(engine)
    columns = [c["name"] for c in inspector.get_columns("hot_terms")]

    if "staged" in columns:
        print("   Ya existe, nada que hacer.")
        return

    dialect = engine.dialect.name
    print(f"   No existe. Agregando (dialecto detectado: {dialect})...")

    with engine.begin() as conn:
        if dialect == "postgresql":
            conn.execute(text("ALTER TABLE hot_terms ADD COLUMN staged BOOLEAN DEFAULT FALSE"))
        else:  # sqlite y la mayoría de otros dialectos aceptan esta sintaxis básica
            conn.execute(text("ALTER TABLE hot_terms ADD COLUMN staged BOOLEAN DEFAULT 0"))

    print("   Columna agregada.")


def add_feedback_calibration_columns_if_missing():
    """Agrega procedencia, revisión y auditoría sin perder filas legacy."""
    print("3. Revisando columnas de feedback/calibración...")
    inspector = inspect(engine)
    dialect = engine.dialect.name
    desired = {
        "feedback": {
            "api_key_hash": "VARCHAR",
            "dataset_version": "INTEGER",
            "term_ids": "TEXT",
            "feedback_fingerprint": "VARCHAR",
        },
        "hot_terms": {
            "initial_weight": "FLOAT",
            "reviewed": (
                "BOOLEAN DEFAULT FALSE" if dialect == "postgresql" else "BOOLEAN DEFAULT 0"
            ),
        },
        "dataset_versions": {
            "status": "VARCHAR DEFAULT 'published'",
            "base_version": "INTEGER",
            "calibration_run_id": "VARCHAR",
            "audit_json": "TEXT",
        },
        "telemetry_snapshots": {
            "shadow_model_counts": "TEXT NOT NULL DEFAULT '{}'",
            "intervention_observed_count": "INTEGER NOT NULL DEFAULT 0",
            "allow_count": "INTEGER NOT NULL DEFAULT 0",
            "silent_observe_count": "INTEGER NOT NULL DEFAULT 0",
            "soft_warn_count": "INTEGER NOT NULL DEFAULT 0",
            "hard_block_count": "INTEGER NOT NULL DEFAULT 0",
            "protective_action_counts": "TEXT NOT NULL DEFAULT '{}'",
        },
    }

    with engine.begin() as conn:
        for table, columns in desired.items():
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, sql_type in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))

        conn.execute(text("UPDATE hot_terms SET initial_weight = weight WHERE initial_weight IS NULL"))
        conn.execute(text("UPDATE hot_terms SET reviewed = 0 WHERE reviewed IS NULL"))
        conn.execute(text("UPDATE dataset_versions SET status = 'published' WHERE status IS NULL"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_feedback_fingerprint "
            "ON feedback (feedback_fingerprint)"
        ))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_dataset_calibration_run "
            "ON dataset_versions (calibration_run_id)"
        ))
    print("   OK.")


def create_initial_api_keys_if_missing():
    print("4. Revisando API keys existentes...")
    db = SessionLocal()
    try:
        existing_count = db.query(db_models.ApiKey).count()
        if existing_count > 0:
            print(f"   Ya hay {existing_count} llave(s) registrada(s). No se genera ninguna nueva.")
            return

        print("   No hay ninguna llave. Generando una admin y una client...")
        now = int(time.time())
        raw_admin_key = f"sk_admin_{secrets.token_urlsafe(32)}"
        raw_client_key = f"sk_client_{secrets.token_urlsafe(32)}"

        db.add(db_models.ApiKey(
            key_hash=hash_api_key(raw_admin_key),
            name="Admin inicial (generada por migrate_production.py)",
            scope="admin",
            created_at=now,
        ))
        db.add(db_models.ApiKey(
            key_hash=hash_api_key(raw_client_key),
            name="Client inicial (generada por migrate_production.py)",
            scope="client",
            created_at=now,
        ))
        db.commit()

        print("\n" + "=" * 70)
        print("  GUARDA ESTAS LLAVES AHORA — no se muestran de nuevo ni se")
        print("  guardan en ningún lado en texto plano, solo su hash SHA-256.")
        print("=" * 70)
        print(f"  ADMIN  : {raw_admin_key}")
        print(f"  CLIENT : {raw_client_key}")
        print("=" * 70 + "\n")
    finally:
        db.close()


def main():
    db_url = os.getenv("DATABASE_URL", "sqlite:///./sentinel.db")
    safe_url = db_url.split("@")[-1] if "@" in db_url else db_url  # oculta credenciales en el log
    print(f"Corriendo migración contra: {safe_url}\n")

    create_missing_tables()
    add_staged_column_if_missing()
    add_feedback_calibration_columns_if_missing()
    create_initial_api_keys_if_missing()

    print("\nMigración completa.")


if __name__ == "__main__":
    main()
