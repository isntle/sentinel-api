from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from src.database import get_db
from src.core.security import require_admin_key
from src.services.network_service import top_risky_actors, purge_expired_sightings

router = APIRouter()

@router.get("/actors", dependencies=[Depends(require_admin_key)])
def list_risky_actors(db: Session = Depends(get_db)):
    """
    Vista administrativa: actores con presencia en múltiples sesiones (posible
    reclutamiento organizado). Solo agregados hasheados, sin identidad en claro.
    """
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": top_risky_actors(db),
    })

@router.post("/purge", dependencies=[Depends(require_admin_key)])
def purge_sightings(db: Session = Depends(get_db)):
    """Fuerza la purga de avistamientos vencidos (retención)."""
    deleted = purge_expired_sightings(db)
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": {"purged": deleted},
    })
