from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.core.security import require_client_key
from src.database import get_db
from src.models.db_models import ApiKey
from src.services.evidence_service import create_or_get_evidence

router = APIRouter()


@router.post("/{session_id}")
def generate_evidence(
    session_id: str,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_client_key),
):
    return create_or_get_evidence(db, session_id, api_key.key_hash)
