from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from abc import ABC, abstractmethod


class SecretStore(ABC):
    @abstractmethod
    def encrypt(self, value: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def decrypt(self, value: str) -> str:
        raise NotImplementedError


class LocalTokenCipher(SecretStore):
    """Authenticated XOR cipher for local/dev token storage. Swap for KMS in production."""

    def __init__(self, secret: str | None = None):
        raw = secret or os.environ.get("TOKEN_ENCRYPTION_KEY") or os.environ.get("JWT_SECRET") or "dev-token-key"
        self._key = hashlib.sha256(raw.encode("utf-8")).digest()

    def encrypt(self, value: str) -> str:
        nonce = secrets.token_bytes(16)
        payload = value.encode("utf-8")
        stream = self._stream(nonce, len(payload))
        cipher = bytes(a ^ b for a, b in zip(payload, stream, strict=True))
        digest = hmac.new(self._key, nonce + cipher, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(nonce + digest + cipher).decode("ascii")

    def decrypt(self, value: str) -> str:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        nonce, digest, cipher = raw[:16], raw[16:48], raw[48:]
        expected = hmac.new(self._key, nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(digest, expected):
            raise ValueError("Invalid encrypted token")
        stream = self._stream(nonce, len(cipher))
        payload = bytes(a ^ b for a, b in zip(cipher, stream, strict=True))
        return payload.decode("utf-8")

    def _stream(self, nonce: bytes, length: int) -> bytes:
        out = bytearray()
        counter = 0
        while len(out) < length:
            out.extend(hmac.new(self._key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
            counter += 1
        return bytes(out[:length])
