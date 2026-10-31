"""Encryption for persisted browser tokens, using the maintained crypto primitive."""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .models import CommerceError


class SecretBox:
    __slots__ = ("_cipher",)

    def __init__(self, key: bytes) -> None:
        if not isinstance(key, bytes) or len(key) != 32:
            raise CommerceError("A separate 32-byte server encryption key is required.")
        self._cipher = AESGCM(key)

    def encrypt(self, value: str, context: str) -> str:
        nonce = os.urandom(12)
        return base64.urlsafe_b64encode(
            nonce + self._cipher.encrypt(nonce, value.encode(), context.encode())
        ).decode()

    def decrypt(self, value: str, context: str) -> str:
        try:
            raw = base64.b64decode(value, altchars=b"-_", validate=True)
            return self._cipher.decrypt(raw[:12], raw[12:], context.encode()).decode()
        except (ValueError, InvalidTag, UnicodeDecodeError):
            raise CommerceError("Persisted checkout token cannot be decrypted.") from None

    def __repr__(self) -> str:
        return "SecretBox(<key redacted>)"
