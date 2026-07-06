from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, Dict, Any, List
import uuid
import json
import time

from src.database import get_db
from src.models.db_models import Feedback
from src.core.security import require_admin_key

router = APIRouter()

class FeedbackRequest(BaseModel):
    session_id: str
    verdict_original: Dict[str, Any]
    feedback: str = Field(..., description="'false_positive' | 'false_negative' | 'confirmed'")
    comment: Optional[str] = None
    reported_by: str

@router.post("")
def report_feedback(body: FeedbackRequest, db: Session = Depends(get_db)):
    """
    Recibe el reporte de feedback de la plataforma cliente.
    """
    if body.feedback not in ['false_positive', 'false_negative', 'confirmed']:
        raise HTTPException(status_code=400, detail="Invalid feedback type")
        
    f = Feedback(
        id=str(uuid.uuid4()),
        session_id=body.session_id,
        verdict_original=json.dumps(body.verdict_original),
        feedback_type=body.feedback,
        comment=body.comment,
        reported_by=body.reported_by,
        created_at=int(time.time())
    )
    db.add(f)
    db.commit()
    
    return JSONResponse(status_code=201, content={
        "success": True,
        "status_code": 201,
        "message": "Feedback registered successfully"
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
            verdict = json.loads(f.verdict_original)
            # Extraemos terminos si vienen en la raiz, o de layers/v3_matches
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
