from sqlalchemy.orm import Session
from src.models.db_models import User, Session as ChatSession, Message as DBMessage
from src.models.conversation import Message as PydanticMessage
from datetime import datetime, timedelta

def get_or_create_user(db: Session, user_uuid: str, dev_user_id: str = "default_user"):
    """Asegura que el usuario exista en la base de datos."""
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        user = User(id=user_uuid, user_id=dev_user_id)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

def _internal_session_id(session_uuid: str, api_key_hash: str | None) -> str:
    if api_key_hash:
        return f"{api_key_hash[:16]}:{session_uuid}"
    return session_uuid

def _public_session_id(internal_id: str) -> str:
    if ":" in internal_id:
        return internal_id.split(":", 1)[1]
    return internal_id

def get_or_create_session(db: Session, session_uuid: str, api_key_hash: str | None = None):
    """Asegura que la sesión exista y calcula la fecha de purga (7 días), asociando el tenant."""
    internal_id = _internal_session_id(session_uuid, api_key_hash)
    session = db.query(ChatSession).filter(ChatSession.id == internal_id).first()
    if not session:
        # Fallback a sesión legacy sin tenant si no se especificó api_key_hash
        if api_key_hash is None:
            legacy = db.query(ChatSession).filter(ChatSession.id == session_uuid).first()
            if legacy:
                return legacy
        now = int(datetime.now().timestamp())
        purge = int((datetime.now() + timedelta(days=7)).timestamp())
        
        session = ChatSession(
            id=internal_id,
            created_at=now,
            last_activity=now,
            purge_at=purge,
            api_key_hash=api_key_hash,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
    return session

def save_message(db: Session, msg_data: PydanticMessage, api_key_hash: str | None = None):
    """Guarda un mensaje y actualiza la última actividad de la sesión."""
    internal_id = _internal_session_id(msg_data.session_id, api_key_hash)
    get_or_create_user(db, msg_data.user_id)
    session = get_or_create_session(db, msg_data.session_id, api_key_hash=api_key_hash)

    # 2. Si el mensaje ya existe, no lo volvemos a insertar
    existing = db.query(DBMessage).filter(DBMessage.id == msg_data.id).first()
    if existing:
        return existing

    # 3. Crear el mensaje
    db_message = DBMessage(
        id=msg_data.id,
        user_id=msg_data.user_id,
        session_id=internal_id,
        content=msg_data.content,
        timestamp=msg_data.timestamp,
    )

    # 4. Actualizar actividad de la sesión
    session.last_activity = msg_data.timestamp

    db.add(db_message)
    db.commit()
    return db_message

def get_session_history(db: Session, session_id: str, api_key_hash: str | None = None):
    """Recupera todos los mensajes de una sesión ordenados por tiempo, filtrando por tenant."""
    internal_id = _internal_session_id(session_id, api_key_hash)
    messages = (
        db.query(DBMessage)
        .filter(DBMessage.session_id == internal_id)
        .order_by(DBMessage.timestamp.asc())
        .all()
    )
    if not messages and api_key_hash is None:
        messages = (
            db.query(DBMessage)
            .filter(DBMessage.session_id == session_id)
            .order_by(DBMessage.timestamp.asc())
            .all()
        )
    return messages

def get_all_messages(db: Session):
    return db.query(DBMessage).order_by(DBMessage.timestamp.asc()).all()

def get_message_by_id(db: Session, message_id: str):
    return db.query(DBMessage).filter(DBMessage.id == message_id).first()

def update_message(db: Session, message_id: str, new_content: str):
    msg = db.query(DBMessage).filter(DBMessage.id == message_id).first()
    if not msg:
        return None
    msg.content = new_content
    db.commit()
    db.refresh(msg)
    return msg

def delete_message(db: Session, message_id: str):
    msg = db.query(DBMessage).filter(DBMessage.id == message_id).first()
    if not msg:
        return False
    db.delete(msg)
    db.commit()
    return True
