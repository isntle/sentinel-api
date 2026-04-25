from fastapi import APIRouter
from src.models.conversation import SyncMessageRequest, Message
from src.controllers.message_controller import handle_sync_message
from typing import List

router = APIRouter()

@router.post("/sync")
def sync_message(request: SyncMessageRequest) -> List[Message]:
    """
    Endpoint para sincronizar un mensaje y obtener historial de sesión.
    """
    return handle_sync_message(request)
