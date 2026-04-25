from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.database import get_db
from src.models.conversation import SyncMessageRequest, Message
from src.controllers.message_controller import handle_sync_message
from typing import List

router = APIRouter()

@router.post("/sync")
def sync_message(
    request: SyncMessageRequest, 
    db: Session = Depends(get_db) # Aquí FastAPI "inyecta" la sesión de DB
) -> List[Message]:
    """
    Endpoint para sincronizar un mensaje y obtener historial de sesión real.
    """
    return handle_sync_message(db, request)
