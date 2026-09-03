"""Cryptographic utility module for encrypting and decrypting user secrets at rest.

Uses AES-128-CBC / HMAC-SHA256 via standard Fernet tokens, with key derivation
from ``settings.ENCRYPTION_SECRET_KEY``.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from cryptography.fernet import Fernet
from ..config import settings

logger = logging.getLogger(__name__)


def _get_fernet_key() -> bytes:
    """Derive a valid 32-byte URL-safe base64 key from settings.ENCRYPTION_SECRET_KEY."""
    raw_hash = hashlib.sha256(settings.ENCRYPTION_SECRET_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(raw_hash)


def encrypt_text(plain_text: str) -> str:
    """Encrypt a plain text secret (e.g. user API key) into a cipher token string."""
    if not plain_text:
        return ""
    try:
        f = Fernet(_get_fernet_key())
        return f.encrypt(plain_text.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        logger.error("Encryption failed: %s", exc)
        return ""


def decrypt_text(cipher_text: str) -> str:
    """Decrypt a cipher token string back to original plain text."""
    if not cipher_text:
        return ""
    try:
        f = Fernet(_get_fernet_key())
        return f.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        logger.warning("Decryption failed: %s", exc)
        return ""
