from sqlalchemy.orm import Session
from src.services.db_service import (
    get_all_messages,
    get_message_by_id,
    update_message,
    delete_message,
)

def handle_get_all(db: Session):
    return get_all_messages(db)

def handle_get_one(db: Session, message_id: str):
    return get_message_by_id(db, message_id)

def handle_update(db: Session, message_id: str, new_content: str):
    return update_message(db, message_id, new_content)

def handle_delete(db: Session, message_id: str):
    return delete_message(db, message_id)
