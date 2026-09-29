"""Generate an Ed25519 key pair for Sentinel artifact signing.

Run once in a secure operator terminal. Store the private value only in the
deployment secret manager; embed/distribute only the public value to clients.
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


private_key = Ed25519PrivateKey.generate()
private_raw = private_key.private_bytes(
    serialization.Encoding.Raw,
    serialization.PrivateFormat.Raw,
    serialization.NoEncryption(),
)
public_raw = private_key.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
)

print(f"ARTIFACT_SIGNING_PRIVATE_KEY={b64url(private_raw)}")
print(f"SENTINEL_ARTIFACT_PUBLIC_KEY={b64url(public_raw)}")
