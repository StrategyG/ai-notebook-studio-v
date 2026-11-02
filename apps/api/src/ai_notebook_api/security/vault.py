from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Mapping
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class VaultConfigurationError(ValueError):
    """The deployment keyring is missing or invalid."""


class VaultDecryptionError(ValueError):
    """A credential cannot be authenticated and decrypted."""


@dataclass(frozen=True, slots=True)
class EncryptedSecret:
    key_id: str
    nonce: bytes
    ciphertext: bytes


@dataclass(frozen=True, slots=True)
class SecretVault:
    keys: Mapping[str, bytes]
    active_key_id: str

    def __post_init__(self) -> None:
        if not self.active_key_id or self.active_key_id not in self.keys:
            raise VaultConfigurationError("active vault key id is missing from the keyring")
        if any(not key_id or len(key_id) > 64 for key_id in self.keys):
            raise VaultConfigurationError("vault key identifiers must be 1..64 characters")
        if any(not isinstance(key, bytes) or len(key) != 32 for key in self.keys.values()):
            raise VaultConfigurationError("AES-256-GCM keys must contain exactly 32 bytes")

    @classmethod
    def from_environment(cls) -> SecretVault:
        raw = os.getenv("PROVIDER_VAULT_KEYS")
        active_key_id = os.getenv("PROVIDER_VAULT_ACTIVE_KEY_ID")
        if not raw or not active_key_id:
            raise VaultConfigurationError("provider vault keyring is not configured")
        try:
            encoded_keys = json.loads(raw)
            if not isinstance(encoded_keys, dict) or not encoded_keys:
                raise ValueError("keyring must be a non-empty JSON object")
            keys = {
                key_id: base64.b64decode(
                    value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
                )
                for key_id, value in encoded_keys.items()
                if isinstance(key_id, str) and isinstance(value, str)
            }
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise VaultConfigurationError("provider vault keyring format is invalid") from exc
        return cls(keys=keys, active_key_id=active_key_id)

    @staticmethod
    def _aad(tenant_id: UUID, credential_id: UUID, provider_id: str) -> bytes:
        return (
            f"ai-notebook-studio:v1:{tenant_id}:{credential_id}:{provider_id}"
        ).encode("utf-8")

    def encrypt(
        self, plaintext: str, *, tenant_id: UUID, credential_id: UUID, provider_id: str
    ) -> EncryptedSecret:
        if not plaintext or len(plaintext.encode("utf-8")) > 16_384:
            raise ValueError("provider secret must be non-empty and at most 16 KiB")
        nonce = os.urandom(12)
        ciphertext = AESGCM(self.keys[self.active_key_id]).encrypt(
            nonce,
            plaintext.encode("utf-8"),
            self._aad(tenant_id, credential_id, provider_id),
        )
        return EncryptedSecret(self.active_key_id, nonce, ciphertext)

    def decrypt(
        self,
        encrypted: EncryptedSecret,
        *,
        tenant_id: UUID,
        credential_id: UUID,
        provider_id: str,
    ) -> str:
        key = self.keys.get(encrypted.key_id)
        if key is None or len(encrypted.nonce) != 12:
            raise VaultDecryptionError("credential key version or nonce is invalid")
        try:
            plaintext = AESGCM(key).decrypt(
                encrypted.nonce,
                encrypted.ciphertext,
                self._aad(tenant_id, credential_id, provider_id),
            )
            return plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise VaultDecryptionError("credential authentication failed") from exc
