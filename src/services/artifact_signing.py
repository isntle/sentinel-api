import base64
import json
import time
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.config import settings


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _load_private_key(value: str) -> Ed25519PrivateKey:
    normalized = value.replace("\\n", "\n").strip()
    if normalized.startswith("-----BEGIN"):
        key = serialization.load_pem_private_key(normalized.encode(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("ARTIFACT_SIGNING_PRIVATE_KEY must be Ed25519")
        return key
    raw = _b64url_decode(normalized)
    if len(raw) != 32:
        raise ValueError("Raw Ed25519 private keys must contain exactly 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(raw)


def build_signed_artifact(
    *,
    kind: str,
    artifact_id: str,
    version: str,
    payload: dict[str, Any],
    now: int | None = None,
) -> dict[str, Any] | None:
    """Signs the exact canonical payload bytes returned to the SDK."""
    private_value = settings.ARTIFACT_SIGNING_PRIVATE_KEY
    if not private_value:
        return None

    issued_at = int(time.time()) if now is None else now
    body = {
        "artifactId": artifact_id,
        "expiresAt": issued_at + settings.ARTIFACT_TTL_SECONDS,
        "format": "sentinel.artifact.v1",
        "issuedAt": issued_at,
        "kind": kind,
        "payload": payload,
        "version": version,
    }
    canonical = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    private_key = _load_private_key(private_value)
    return {
        "algorithm": "Ed25519",
        "format": "sentinel.envelope.v1",
        "keyId": settings.ARTIFACT_SIGNING_KEY_ID,
        "payload": _b64url(canonical),
        "signature": _b64url(private_key.sign(canonical)),
    }


def artifact_public_key() -> str | None:
    """Returns raw public bytes for deployment tooling, never the private key."""
    if not settings.ARTIFACT_SIGNING_PRIVATE_KEY:
        return None
    key = _load_private_key(settings.ARTIFACT_SIGNING_PRIVATE_KEY).public_key()
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return _b64url(raw)
