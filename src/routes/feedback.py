from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, Dict, Any, List
import uuid
import json
import time

from src.database import get_db
from src.models.db_models import ApiKey, Feedback
from src.core.security import require_admin_key, require_client_key
import hashlib
import re

router = APIRouter()

class FeedbackRequest(BaseModel):
    session_id: str
    verdict_original: Dict[str, Any]
    feedback: str = Field(..., description="'false_positive' | 'false_negative' | 'confirmed'")
    comment: Optional[str] = None
    reported_by: str
    term_ids: List[str] = Field(default_factory=list, max_length=100)
    dataset_version: Optional[int] = Field(default=None, ge=1)

    @field_validator("term_ids")
    @classmethod
    def validate_term_ids(cls, values: List[str]) -> List[str]:
        editorial = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$")
        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        )
        normalized = list(dict.fromkeys(value.strip() for value in values))
        if any(
            len(value) > 80
            or not (editorial.fullmatch(value) or uuid_pattern.fullmatch(value))
            for value in normalized
        ):
            raise ValueError("term_ids must contain dataset IDs, never message text")
        return normalized

@router.post("")
def report_feedback(
    body: FeedbackRequest,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_client_key),
):
    """
    Recibe el reporte de feedback de la plataforma cliente.
    """
    if body.feedback not in ['false_positive', 'false_negative', 'confirmed']:
        raise HTTPException(status_code=400, detail="Invalid feedback type")
        
    fingerprint_source = json.dumps(
        {
            "api_key_hash": api_key.key_hash,
            "session_id": body.session_id,
            "feedback": body.feedback,
            "term_ids": sorted(body.term_ids),
            "dataset_version": body.dataset_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(fingerprint_source.encode()).hexdigest()
    existing = db.query(Feedback).filter(Feedback.feedback_fingerprint == fingerprint).first()
    if existing:
        return JSONResponse(status_code=200, content={
            "success": True,
            "status_code": 200,
            "message": "Feedback already registered",
            "data": {"id": existing.id, "deduplicated": True},
        })

    f = Feedback(
        id=str(uuid.uuid4()),
        session_id=body.session_id,
        verdict_original=json.dumps(body.verdict_original),
        feedback_type=body.feedback,
        comment=body.comment,
        reported_by=body.reported_by,
        created_at=int(time.time()),
        api_key_hash=api_key.key_hash,
        dataset_version=body.dataset_version,
        term_ids=json.dumps(body.term_ids, separators=(",", ":")),
        feedback_fingerprint=fingerprint,
    )
    db.add(f)
    db.commit()
    
    return JSONResponse(status_code=201, content={
        "success": True,
        "status_code": 201,
        "message": "Feedback registered successfully",
        "data": {"id": f.id, "deduplicated": False},
    })

@router.get("/stats", dependencies=[Depends(require_admin_key)])
def get_feedback_stats(db: Session = Depends(get_db)):
    """
    Endpoint administrativo: Calcula la tasa de falsos positivos (FP) por término.
    Requiere llave admin — expone datos agregados de todos los clientes.
    """
    all_feedback = db.query(Feedback).all()
    
    term_stats = {}
    
    for f in all_feedback:
        try:
            # Filas nuevas guardan IDs validados por separado. El veredicto se
            # conserva únicamente como fallback para las filas legacy.
            terms = json.loads(f.term_ids) if f.term_ids else []
            verdict = json.loads(f.verdict_original)
            if not terms:
                terms = verdict.get('terms', [])
            
            # Formato Sentinel SDK: Si los terminos vienen en layers
            if not terms and 'layers' in verdict:
                layers = verdict['layers']
                if 'v3_matches' in layers:
                    terms = [m.get('term') for m in layers['v3_matches']]
            
            for term in terms:
                if not term:
                    continue
                if term not in term_stats:
                    term_stats[term] = {"total_reports": 0, "false_positives": 0, "confirmed": 0, "false_negatives": 0}
                
                term_stats[term]["total_reports"] += 1
                if f.feedback_type == "false_positive":
                    term_stats[term]["false_positives"] += 1
                elif f.feedback_type == "confirmed":
                    term_stats[term]["confirmed"] += 1
                elif f.feedback_type == "false_negative":
                    term_stats[term]["false_negatives"] += 1
        except Exception:
            continue
            
    # Calculate FP rate
    result = []
    for term, stats in term_stats.items():
        fp_rate = (stats["false_positives"] / stats["total_reports"]) * 100 if stats["total_reports"] > 0 else 0
        result.append({
            "term": term,
            "total_reports": stats["total_reports"],
            "false_positives": stats["false_positives"],
            "confirmed": stats["confirmed"],
            "false_negatives": stats["false_negatives"],
            "fp_rate_percent": round(fp_rate, 2)
        })
        
    # Sort by FP count descending
    result.sort(key=lambda x: x["false_positives"], reverse=True)
    
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": result
    })
