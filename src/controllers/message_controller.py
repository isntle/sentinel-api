from sqlalchemy.orm import Session
from src.models.conversation import SyncMessageRequest, Message
from src.services.db_service import save_message, get_session_history
from typing import List
import uuid

def handle_sync_message(db: Session, request: SyncMessageRequest) -> List[Message]:
    """
    Usa la sesión de DB para persistir el mensaje y recuperar el historial real.
    """
    # 1. Generar el id del mensaje en la API
    full_message = Message(
        id=str(uuid.uuid4()),
        user_id=request.message.user_id,
        session_id=request.message.session_id,
        content=request.message.content,
        timestamp=request.message.timestamp,
    )

    save_message(db, full_message)
    
    # 2. Recuperar todo el historial de esa sesión desde la DB
    db_history = get_session_history(db, request.message.session_id, request.message.user_id)
    
    # 3. Convertir los objetos de la DB al formato que el SDK entiende (Pydantic)
    history = [
        Message(
            id=m.id,
            user_id=m.user_id,
            session_id=m.session_id,
            content=m.content,
            timestamp=m.timestamp
        ) for m in db_history
    ]
    
    return history
