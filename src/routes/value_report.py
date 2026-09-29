from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from src.core.security import require_client_key
from src.database import get_db
from src.models.db_models import ApiKey
from src.services.monthly_value_service import (
    build_monthly_value_report,
    render_monthly_value_html,
)

router = APIRouter()


@router.get("/monthly")
def monthly_value_report(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    format: Literal["json", "html"] = Query(default="json"),
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_client_key),
):
    now = datetime.now(timezone.utc)
    try:
        report = build_monthly_value_report(
            db,
            api_key.key_hash,
            api_key.name,
            year or now.year,
            month or now.month,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if format == "html":
        return HTMLResponse(
            render_monthly_value_html(report),
            headers={"Cache-Control": "private, no-store"},
        )
    return {"success": True, "data": report}
