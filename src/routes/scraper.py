from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from src.database import get_db
from src.services.scraper_service import run_scraper

router = APIRouter()

@router.post("")
async def trigger_scraper(db: Session = Depends(get_db)):
    """
    Dispara el scraping manual o automático (Railway cron).
    Escanea fuentes de noticias mexicanas, extrae términos candidatos
    y los clasifica con Groq. Los aprobados quedan disponibles para el SDK.
    """
    results = await run_scraper(db)
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": results,
    })
