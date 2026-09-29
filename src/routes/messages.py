from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from src.database import get_db
from src.models.conversation import SyncMessageRequest
from src.controllers.message_controller import handle_sync_message
from src.core.security import require_client_key
from src.models.db_models import ApiKey

router = APIRouter()

@router.post("/sync")
def sync_message(
    request: SyncMessageRequest,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_client_key),
):
    history = handle_sync_message(db, request, api_key_hash=api_key.key_hash)
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "status_code": 200,
            "data": [m.model_dump() for m in history],
        },
    )
