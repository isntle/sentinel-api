from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from src.database import get_db
from src.models.conversation import SyncMessageRequest
from src.controllers.message_controller import handle_sync_message

router = APIRouter()

@router.post("/sync")
def sync_message(request: SyncMessageRequest, db: Session = Depends(get_db)):
    history = handle_sync_message(db, request)
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "status_code": 200,
            "data": [m.model_dump() for m in history],
        },
    )
