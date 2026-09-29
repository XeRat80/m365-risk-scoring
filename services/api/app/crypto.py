from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretCipher:
    """Authenticated encryption for connector credentials stored in PostgreSQL."""

    def __init__(self, master_key: str) -> None:
        self._cipher = AESGCM(hashlib.sha256(master_key.encode()).digest())

    def encrypt(self, plaintext: str, tenant_id: str) -> str:
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(nonce, plaintext.encode(), tenant_id.encode())
        return base64.urlsafe_b64encode(nonce + ciphertext).decode()

    def decrypt(self, token: str, tenant_id: str) -> str:
        payload = base64.urlsafe_b64decode(token.encode())
        return self._cipher.decrypt(payload[:12], payload[12:], tenant_id.encode()).decode()
