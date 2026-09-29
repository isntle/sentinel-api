import json
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.core.security import require_admin_key, require_client_key
from src.database import get_db
from src.models.db_models import ShadowModelArtifact, ShadowModelRelease
from src.models.shadow_model import ShadowModelPayload
from src.services.artifact_signing import build_signed_artifact

router = APIRouter()


@router.post("/stage", status_code=201, dependencies=[Depends(require_admin_key)])
def stage_shadow_model(
    body: ShadowModelPayload,
    db: Session = Depends(get_db),
):
    if db.get(ShadowModelArtifact, body.modelId):
        raise HTTPException(status_code=409, detail="Model ID already exists")
    artifact = ShadowModelArtifact(
        model_id=body.modelId,
        feature_schema_version=body.schemaVersion,
        payload_json=body.model_dump_json(),
        created_at=int(time.time()),
        staged=True,
    )
    db.add(artifact)
    db.commit()
    return {"success": True, "data": {"model_id": body.modelId, "staged": True}}


def _release(model_id: str, action: str, db: Session):
    artifact = db.get(ShadowModelArtifact, model_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Model not found")
    artifact.staged = False
    release = ShadowModelRelease(
        model_id=model_id,
        created_at=int(time.time()),
        action=action,
    )
    db.add(release)
    db.commit()
    db.refresh(release)
    return {
        "success": True,
        "data": {
            "release_version": release.version,
            "model_id": model_id,
            "action": action,
        },
    }


@router.post("/publish/{model_id}", dependencies=[Depends(require_admin_key)])
def publish_shadow_model(model_id: str, db: Session = Depends(get_db)):
    return _release(model_id, "publish", db)


@router.post("/rollback/{model_id}", dependencies=[Depends(require_admin_key)])
def rollback_shadow_model(model_id: str, db: Session = Depends(get_db)):
    # El rollback no reutiliza una versión anterior: crea una release nueva y
    # monotónica, por lo que la protección anti-rollback del SDK permanece útil.
    return _release(model_id, "rollback", db)


@router.get("/current", dependencies=[Depends(require_client_key)])
def current_shadow_model(db: Session = Depends(get_db)):
    release = (
        db.query(ShadowModelRelease)
        .order_by(ShadowModelRelease.version.desc())
        .first()
    )
    if release is None:
        raise HTTPException(status_code=404, detail="No shadow model published")
    artifact = db.get(ShadowModelArtifact, release.model_id)
    if artifact is None:
        raise HTTPException(status_code=500, detail="Published model artifact missing")
    model = json.loads(artifact.payload_json)
    payload = {"releaseVersion": release.version, "model": model}
    signed = build_signed_artifact(
        kind="shadow_model",
        artifact_id="shadow-classifier",
        version=f"release.{release.version}",
        payload=payload,
    )
    return {
        "success": True,
        "data": payload,
        "artifact": signed,
    }
