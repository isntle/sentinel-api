"""
Servicio de mantenimiento y retención de datos para Sentinel (S21).

Garantiza:
1. Purga periódica de mensajes crudos expirados (>30 días) para minimizar retención de datos sensibles.
2. Protección de Legal Hold: conservación de paquetes de evidencia seudónima de incidentes confirmados.
3. Utilidades de respaldo y restauración deterministas para base de datos SQLite.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import time
from sqlalchemy.orm import Session
from src.models.db_models import Message, Session as DBSession, EvidencePackage


def purge_expired_messages(
    db: Session,
    retention_days: int = 30,
    legal_hold_days: int = 365,
) -> dict[str, int]:
    """
    Purga mensajes crudos que superan retention_days, preservando aquellos
    amparados por paquetes de evidencia seudónima bajo Legal Hold.
    """
    now = int(time.time())
    cutoff_regular = now - (retention_days * 86400)
    cutoff_legal_hold = now - (legal_hold_days * 86400)

    # Identificar sesiones con paquetes de evidencia bajo Legal Hold
    legal_hold_sessions = {
        ep.session_id for ep in db.query(EvidencePackage.session_id).all()
    }

    # 1. Mensajes normales expirados (sin legal hold)
    query_regular = db.query(Message).filter(
        Message.timestamp < cutoff_regular,
        ~Message.session_id.in_(legal_hold_sessions) if legal_hold_sessions else True
    )
    purged_regular_count = query_regular.count()
    query_regular.delete(synchronize_session=False)

    # 2. Mensajes bajo Legal Hold pero que ya superaron el plazo máximo de retención legal (365 días)
    purged_legal_count = 0
    if legal_hold_sessions:
        query_legal = db.query(Message).filter(
            Message.timestamp < cutoff_legal_hold,
            Message.session_id.in_(legal_hold_sessions)
        )
        purged_legal_count = query_legal.count()
        query_legal.delete(synchronize_session=False)

    db.commit()

    return {
        "purged_regular_messages": purged_regular_count,
        "purged_legal_hold_messages": purged_legal_count,
        "total_purged": purged_regular_count + purged_legal_count,
    }


def backup_sqlite_database(source_db_path: str, destination_backup_path: str) -> bool:
    """Copia y asegura un respaldo íntegro de la base de datos SQLite."""
    if not os.path.exists(source_db_path):
        raise FileNotFoundError(f"Base de datos origen no encontrada: {source_db_path}")

    os.makedirs(os.path.dirname(os.path.abspath(destination_backup_path)), exist_ok=True)
    
    # Uso de la API de backup en línea de SQLite para consistencia atómica
    src_conn = sqlite3.connect(source_db_path)
    dst_conn = sqlite3.connect(destination_backup_path)
    try:
        with dst_conn:
            src_conn.backup(dst_conn)
        return True
    finally:
        dst_conn.close()
        src_conn.close()


def restore_sqlite_database(backup_path: str, target_db_path: str) -> bool:
    """Restaura la base de datos a partir de un archivo de respaldo verificado."""
    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Archivo de respaldo no encontrado: {backup_path}")

    # Verificar que el backup sea una base de datos SQLite válida
    conn = sqlite3.connect(backup_path)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA quick_check;")
        res = cursor.fetchone()
        if not res or res[0] != "ok":
            raise ValueError(f"El archivo de respaldo está corrupto: {res}")
    finally:
        conn.close()

    # Sobrescribir archivo destino
    os.makedirs(os.path.dirname(os.path.abspath(target_db_path)), exist_ok=True)
    shutil.copy2(backup_path, target_db_path)
    return True
