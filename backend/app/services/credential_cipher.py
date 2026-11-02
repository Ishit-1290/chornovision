"""Encryption of per-camera stream credentials at rest (Phase 10; D-64).

Cameras frequently require RTSP authentication, but the Phase 3 policy deliberately rejected
URLs with embedded ``user:pass@`` userinfo so credentials could never be stored or echoed. This
module adds an explicit, separate store for a camera's credential pair:

* The pair is serialised as JSON and encrypted with **Fernet** (AES-128-CBC + HMAC-SHA256).
* The key is derived from ``SECRET_KEY`` with SHA-256 and a domain-separation prefix, so no
  second secret has to be provisioned and rotating ``SECRET_KEY`` invalidates stored
  credentials (they must be re-entered; playback then reports a non-sensitive error).
* The ciphertext is the only form persisted; it is never returned by an API, logged, or
  included in an error message. Callers that need the plaintext are the internal gateway
  registration path only.
"""

from __future__ import annotations

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

#: Version prefix so a future key/algorithm change is detectable rather than mis-decrypted.
_PREFIX = "v1:"
_KEY_CONTEXT = b"chronovision/camera-stream-credentials/v1"


class CredentialError(Exception):
    """Stored stream credentials could not be decrypted (wrong key or corruption)."""


def _fernet() -> Fernet:
    secret = get_settings().secret_key.get_secret_value().encode("utf-8")
    digest = hashlib.sha256(_KEY_CONTEXT + b"\x00" + secret).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_credentials(username: str, password: str) -> str:
    """Encrypt a credential pair into an opaque, storable token."""
    payload = json.dumps(
        {"username": username, "password": password},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return _PREFIX + _fernet().encrypt(payload).decode("ascii")


def decrypt_credentials(token: str) -> tuple[str, str]:
    """Decrypt a token produced by :func:`encrypt_credentials`.

    Raises :class:`CredentialError` (never leaking the input) when the token is
    malformed, uses an unknown version, or cannot be authenticated with the current key.
    """
    if not token.startswith(_PREFIX):
        raise CredentialError("unsupported credential encoding")
    try:
        raw = _fernet().decrypt(token[len(_PREFIX) :].encode("ascii"))
        data = json.loads(raw)
        username = data["username"]
        password = data["password"]
    except (InvalidToken, ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise CredentialError("stored stream credentials could not be decrypted") from exc
    if not isinstance(username, str) or not isinstance(password, str):
        raise CredentialError("stored stream credentials are malformed")
    return username, password
