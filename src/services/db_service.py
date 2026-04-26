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

def get_or_create_session(db: Session, session_uuid: str):
    """Asegura que la sesión exista y calcula la fecha de purga (7 días)."""
    session = db.query(ChatSession).filter(ChatSession.id == session_uuid).first()
    if not session:
        now = int(datetime.now().timestamp())
        purge = int((datetime.now() + timedelta(days=7)).timestamp())
        
        session = ChatSession(
            id=session_uuid,
            created_at=now,
            last_activity=now,
            purge_at=purge
        )
        db.add(session)
        db.commit()
        db.refresh(session)
    return session

def save_message(db: Session, msg_data: PydanticMessage):
    """Guarda un mensaje y actualiza la última actividad de la sesión."""
    # 1. Asegurar User y Session
    get_or_create_user(db, msg_data.user_id)
    session = get_or_create_session(db, msg_data.session_id)

    # 2. Si el mensaje ya existe, no lo volvemos a insertar
    existing = db.query(DBMessage).filter(DBMessage.id == msg_data.id).first()
    if existing:
        return existing

    # 3. Crear el mensaje
    db_message = DBMessage(
        id=msg_data.id,
        user_id=msg_data.user_id,
        session_id=msg_data.session_id,
        content=msg_data.content,
        timestamp=msg_data.timestamp
    )

    # 4. Actualizar actividad de la sesión
    session.last_activity = msg_data.timestamp

    db.add(db_message)
    db.commit()
    return db_message

def get_session_history(db: Session, session_id: str, user_id: str):
    """Recupera los mensajes de un usuario en una sesión ordenados por tiempo."""
    return (
        db.query(DBMessage)
        .filter(DBMessage.session_id == session_id, DBMessage.user_id == user_id)
        .order_by(DBMessage.timestamp.asc())
        .all()
    )

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
