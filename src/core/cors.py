from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def configure_cors(app: FastAPI, allowed_origins: Sequence[str]) -> None:
    """Autoriza solo los orígenes declarados; vacío mantiene CORS cerrado."""
    if not allowed_origins:
        return
    if "*" in allowed_origins:
        raise ValueError("CORS wildcard is forbidden; configure explicit platform origins")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key"],
        expose_headers=["X-Process-Time"],
        max_age=600,
    )
