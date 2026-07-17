from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from src.database import get_db
from src.services.scraper_service import run_scraper
from src.models.db_models import AnalysisRecord, ScraperRun, Message
import time
import uuid
import json

router = APIRouter()

def purge_expired(db: Session, days: int = 7):
    cutoff = int(time.time()) - (days * 24 * 60 * 60)
    deleted = db.query(Message).filter(Message.timestamp < cutoff).delete(synchronize_session=False)
    # Los snapshots temporales del análisis siguen la misma retención. Los
    # EvidencePackage creados explícitamente son legal holds independientes y
    # jamás se incluyen en este job.
    now = int(time.time())
    db.query(AnalysisRecord).filter(AnalysisRecord.purge_at < now).delete(
        synchronize_session=False
    )
    db.commit()
    # También purga los avistamientos de red vencidos (retención 30 días).
    from src.services.network_service import purge_expired_sightings
    purge_expired_sightings(db)
    return deleted

@router.post("")
def trigger_scraper(db: Session = Depends(get_db)):
    """
    Dispara el scraping manual o automático (Railway cron).
    Escanea fuentes de noticias mexicanas, extrae términos candidatos
    y los clasifica con Groq. Los aprobados quedan disponibles para el SDK.
    """
    # 1. Purge expired messages before running scraper
    deleted_msgs = purge_expired(db)
    
    # 2. Record run start
    run_id = str(uuid.uuid4())
    run = ScraperRun(id=run_id, started_at=int(time.time()), status="running")
    db.add(run)
    db.commit()
    
    try:
        results = run_scraper(db)
        results["purged_messages"] = deleted_msgs
        run.status = "success"
        run.finished_at = int(time.time())
        run.results = json.dumps(results)
    except Exception as e:
        run.status = "failed"
        run.finished_at = int(time.time())
        run.error = str(e)
        db.commit()
        return JSONResponse(status_code=500, content={
            "success": False,
            "status_code": 500,
            "message": "Error ejecutando el scraper",
            "error": str(e)
        })
        
    db.commit()
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": results,
    })

@router.get("/runs")
def get_scraper_runs(db: Session = Depends(get_db)):
    runs = db.query(ScraperRun).order_by(ScraperRun.started_at.desc()).limit(20).all()
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": [
            {
                "id": r.id,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "status": r.status,
                "results": json.loads(r.results) if r.results else None,
                "error": r.error
            } for r in runs
        ]
    })
