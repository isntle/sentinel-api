import hashlib
import json
import time
import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.models.conversation import EscalationRequest
from src.models.db_models import AnalysisRecord, DatasetVersion, EvidencePackage

CANONICAL_SEPARATORS = (",", ":")
EVIDENCE_SCHEMA_VERSION = "1.0"
ELIGIBLE_RISKS = {"HIGH", "CRITICAL"}


def canonical_json(content: dict) -> str:
    """Representación UTF-8 estable usada tanto para guardar como para hashear."""
    return json.dumps(
        content,
        sort_keys=True,
        separators=CANONICAL_SEPARATORS,
        ensure_ascii=False,
    )


def content_sha256(content: dict) -> str:
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


def _dataset_snapshot(db: Session, escalation: EscalationRequest) -> dict:
    reported = escalation.datasetVersions
    hot_terms = None
    if reported and reported.apiHotTerms is not None:
        version = (
            db.query(DatasetVersion)
            .filter(DatasetVersion.version == reported.apiHotTerms)
            .first()
        )
        if version:
            hot_terms = {
                "version": version.version,
                "created_at": version.created_at,
                "description": version.description,
            }
        else:
            # Conserva lo declarado sin fingir que la API pudo verificarlo.
            hot_terms = {
                "version": reported.apiHotTerms,
                "verified_in_api": False,
            }

    return {
        "sdk_region_packs": dict(reported.regionPacks) if reported else {},
        "api_hot_terms": hot_terms,
    }


def record_eligible_analysis(
    db: Session,
    escalation: EscalationRequest,
    llm_verdict: dict,
    api_key_hash: str,
) -> AnalysisRecord | None:
    """Persiste la entrada y salida HIGH/CRITICAL durante siete días."""
    risk = escalation.risk.upper()
    if risk not in ELIGIBLE_RISKS:
        return None

    now = int(time.time())
    session_id = escalation.messages[0].session_id
    if any(message.session_id != session_id for message in escalation.messages):
        raise ValueError("All messages in an escalation must belong to the same session")

    record = AnalysisRecord(
        id=str(uuid.uuid4()),
        session_id=session_id,
        api_key_hash=api_key_hash,
        risk=risk,
        analysis_payload=canonical_json(escalation.model_dump(mode="json")),
        llm_verdict=canonical_json(llm_verdict),
        dataset_versions=canonical_json(_dataset_snapshot(db, escalation)),
        created_at=now,
        purge_at=now + int(timedelta(days=7).total_seconds()),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _package_response(package: EvidencePackage) -> dict:
    payload = json.loads(package.canonical_payload)
    calculated = content_sha256(payload)
    if calculated != package.content_hash:
        raise RuntimeError("Stored evidence package failed its integrity check")
    return {
        "payload": payload,
        "integrity": {
            "algorithm": "SHA-256",
            "canonicalization": (
                "json.dumps(sort_keys=True,separators=(',', ':'),ensure_ascii=False)"
            ),
            "content_hash": package.content_hash,
        },
    }


def create_or_get_evidence(db: Session, session_id: str, api_key_hash: str) -> dict:
    record = (
        db.query(AnalysisRecord)
        .filter(
            AnalysisRecord.session_id == session_id,
            AnalysisRecord.api_key_hash == api_key_hash,
            AnalysisRecord.risk.in_(ELIGIBLE_RISKS),
        )
        .order_by(AnalysisRecord.created_at.desc(), AnalysisRecord.id.desc())
        .first()
    )
    if not record:
        raise HTTPException(
            status_code=404,
            detail="No eligible HIGH/CRITICAL analysis exists for this session",
        )

    existing = (
        db.query(EvidencePackage)
        .filter(EvidencePackage.analysis_record_id == record.id)
        .first()
    )
    if existing:
        return _package_response(existing)

    analysis = json.loads(record.analysis_payload)
    messages = sorted(
        analysis.pop("messages"),
        key=lambda message: (message["timestamp"], message["id"]),
    )
    analysis.pop("datasetVersions", None)
    evidence_id = str(uuid.uuid4())
    generated_at = int(time.time())
    payload = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_id": evidence_id,
        "analysis_record_id": record.id,
        "session_id": record.session_id,
        "generated_at": generated_at,
        "analysis_recorded_at": record.created_at,
        "messages": messages,
        "engine_result": analysis,
        "llm_verdict": json.loads(record.llm_verdict),
        "dataset_versions": json.loads(record.dataset_versions),
        "retention": {
            "explicit_legal_hold": True,
            "normal_automatic_purge_exempt": True,
        },
    }
    package = EvidencePackage(
        id=evidence_id,
        analysis_record_id=record.id,
        session_id=record.session_id,
        api_key_hash=api_key_hash,
        canonical_payload=canonical_json(payload),
        content_hash=content_sha256(payload),
        created_at=generated_at,
    )
    db.add(package)
    try:
        db.commit()
        db.refresh(package)
    except IntegrityError:
        # Dos solicitudes simultáneas: la restricción unique decide cuál ganó.
        db.rollback()
        package = (
            db.query(EvidencePackage)
            .filter(EvidencePackage.analysis_record_id == record.id)
            .one()
        )
    return _package_response(package)
