from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from src.database import get_db
from src.controllers.messages_crud_controller import (
    handle_get_all,
    handle_get_one,
    handle_update,
    handle_delete,
)

router = APIRouter()

class UpdateMessageBody(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)

def message_to_dict(m) -> dict:
    return {
        "id": m.id,
        "user_id": m.user_id,
        "session_id": m.session_id,
        "content": m.content,
        "timestamp": m.timestamp,
    }

@router.get("")
def get_all_messages(db: Session = Depends(get_db)):
    messages = handle_get_all(db)
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": [message_to_dict(m) for m in messages],
    })

@router.get("/{message_id}")
def get_message(message_id: str, db: Session = Depends(get_db)):
    msg = handle_get_one(db, message_id)
    if not msg:
        return JSONResponse(status_code=404, content={
            "success": False,
            "status_code": 404,
            "details": f"No existe un mensaje con id '{message_id}'.",
        })
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": message_to_dict(msg),
    })

@router.patch("/{message_id}")
def update_message(message_id: str, body: UpdateMessageBody, db: Session = Depends(get_db)):
    msg = handle_update(db, message_id, body.content)
    if not msg:
        return JSONResponse(status_code=404, content={
            "success": False,
            "status_code": 404,
            "details": f"No existe un mensaje con id '{message_id}'.",
        })
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": message_to_dict(msg),
    })

@router.delete("/{message_id}")
def delete_message(message_id: str, db: Session = Depends(get_db)):
    deleted = handle_delete(db, message_id)
    if not deleted:
        return JSONResponse(status_code=404, content={
            "success": False,
            "status_code": 404,
            "details": f"No existe un mensaje con id '{message_id}'.",
        })
    return JSONResponse(status_code=200, content={
        "success": True,
        "status_code": 200,
        "data": f"Mensaje '{message_id}' eliminado correctamente.",
    })
