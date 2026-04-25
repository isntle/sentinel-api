from src.models.conversation import SyncMessageRequest, Message
from typing import List

def handle_sync_message(request: SyncMessageRequest) -> List[Message]:
    """
    Lógica para guardar el mensaje en la DB y recuperar el historial.
    """
    # TODO: Integrar con SQLAlchemy para persistir el mensaje
    # TODO: Consultar historial de la sesión en la tabla Messages
    
    # Por ahora devolvemos una lista vacía o el mismo mensaje 
    # hasta que se conecte la persistencia real.
    return []
