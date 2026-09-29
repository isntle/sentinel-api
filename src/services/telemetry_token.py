import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time

from src.config.settings import TELEMETRY_TOKEN_SECRET

TOKEN_TTL_SECONDS = 300


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    # Base64 puede tener representaciones textuales distintas que producen los
    # mismos bytes por los bits de relleno. Exigir la forma canónica garantiza
    # que cualquier modificación del token sea rechazada, incluso en el último
    # carácter de la firma.
    if _b64url_encode(decoded) != value:
        raise binascii.Error("non-canonical base64url")
    return decoded


def issue_telemetry_token(api_key_hash: str, now: int | None = None) -> tuple[str, int]:
    issued_at = int(time.time()) if now is None else now
    expires_at = issued_at + TOKEN_TTL_SECONDS
    payload = {
        "aud": "sentinel-telemetry",
        "exp": expires_at,
        "key_hash": api_key_hash,
        "nonce": secrets.token_urlsafe(12),
    }
    encoded = _b64url_encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = hmac.new(
        TELEMETRY_TOKEN_SECRET.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded}.{_b64url_encode(signature)}", expires_at


def verify_telemetry_token(token: str, now: int | None = None) -> str | None:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = hmac.new(
            TELEMETRY_TOKEN_SECRET.encode("utf-8"),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(_b64url_decode(supplied_signature), expected_signature):
            return None
        payload = json.loads(_b64url_decode(encoded))
        current_time = int(time.time()) if now is None else now
        if payload.get("aud") != "sentinel-telemetry":
            return None
        if not isinstance(payload.get("exp"), int) or payload["exp"] <= current_time:
            return None
        key_hash = payload.get("key_hash")
        return key_hash if isinstance(key_hash, str) and len(key_hash) == 64 else None
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, binascii.Error):
        return None
