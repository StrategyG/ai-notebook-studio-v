import base64
import json
from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ai_notebook_api.db.base import Base
from ai_notebook_api.db.models import AuditEvent, ProviderCredential
from ai_notebook_api.security.vault import (
    EncryptedSecret,
    SecretVault,
    VaultConfigurationError,
    VaultDecryptionError,
)
from ai_notebook_api.services.audit import verify_audit_chain
from ai_notebook_api.services.provider_credentials import (
    create_provider_credential,
    get_provider_secret,
    revoke_provider_credential,
)

TENANT_A = UUID("d2719d9a-3b0a-4b8a-a95b-1a8a1efc7f8e")
TENANT_B = UUID("a8e49d50-9f30-4bde-9c6f-4a7d84b0d21c")


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def vault(key_id: str = "k1", key: bytes = b"a" * 32) -> SecretVault:
    return SecretVault(keys={key_id: key}, active_key_id=key_id)


def test_secret_vault_encrypts_and_decrypts_with_tenant_bound_aad() -> None:
    current = vault()
    credential_id = UUID("c5a19d50-9f30-4bde-9c6f-4a7d84b0d21c")
    encrypted = current.encrypt(
        "sk-test-secret", tenant_id=TENANT_A, credential_id=credential_id, provider_id="openai"
    )

    assert encrypted.ciphertext != b"sk-test-secret"
    assert current.decrypt(
        encrypted, tenant_id=TENANT_A, credential_id=credential_id, provider_id="openai"
    ) == "sk-test-secret"
    with pytest.raises(VaultDecryptionError):
        current.decrypt(
            encrypted, tenant_id=TENANT_B, credential_id=credential_id, provider_id="openai"
        )


def test_secret_vault_supports_key_rotation_without_reencrypting_old_values() -> None:
    old_vault = vault("old", b"o" * 32)
    credential_id = UUID("c5a19d50-9f30-4bde-9c6f-4a7d84b0d21c")
    encrypted = old_vault.encrypt(
        "secret", tenant_id=TENANT_A, credential_id=credential_id, provider_id="openai"
    )
    rotated = SecretVault(
        keys={"old": b"o" * 32, "new": b"n" * 32},
        active_key_id="new",
    )

    assert rotated.decrypt(
        encrypted, tenant_id=TENANT_A, credential_id=credential_id, provider_id="openai"
    ) == "secret"
    assert rotated.encrypt(
        "next", tenant_id=TENANT_A, credential_id=credential_id, provider_id="openai"
    ).key_id == "new"


def test_secret_vault_detects_ciphertext_tampering() -> None:
    current = vault()
    credential_id = UUID("c5a19d50-9f30-4bde-9c6f-4a7d84b0d21c")
    encrypted = current.encrypt(
        "secret", tenant_id=TENANT_A, credential_id=credential_id, provider_id="openai"
    )
    tampered = EncryptedSecret(
        key_id=encrypted.key_id,
        nonce=encrypted.nonce,
        ciphertext=encrypted.ciphertext[:-1] + bytes([encrypted.ciphertext[-1] ^ 1]),
    )
    with pytest.raises(VaultDecryptionError):
        current.decrypt(
            tampered, tenant_id=TENANT_A, credential_id=credential_id, provider_id="openai"
        )


def test_vault_environment_configuration_is_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv("PROVIDER_VAULT_KEYS", raising=False)
    monkeypatch.delenv("PROVIDER_VAULT_ACTIVE_KEY_ID", raising=False)
    with pytest.raises(VaultConfigurationError):
        SecretVault.from_environment()

    encoded = base64.urlsafe_b64encode(b"z" * 32).decode().rstrip("=")
    monkeypatch.setenv("PROVIDER_VAULT_KEYS", json.dumps({"active": encoded}))
    monkeypatch.setenv("PROVIDER_VAULT_ACTIVE_KEY_ID", "active")
    assert SecretVault.from_environment().active_key_id == "active"


def test_provider_secret_is_encrypted_persisted_and_audited(session: Session) -> None:
    credential = create_provider_credential(
        session,
        vault=vault(),
        tenant_id=TENANT_A,
        provider_id="openai",
        label="primary",
        plaintext_secret="sk-live-test",
        created_by="user-1",
        request_id="req-create",
    )
    session.commit()

    stored = session.scalar(
        select(ProviderCredential).where(ProviderCredential.id == credential.id)
    )
    assert stored is not None
    assert b"sk-live-test" not in stored.encrypted_secret
    assert get_provider_secret(
        session, vault=vault(), tenant_id=TENANT_A, credential_id=credential.id
    ) == "sk-live-test"
    assert verify_audit_chain(session, tenant_id=TENANT_A)
    assert session.scalar(select(AuditEvent).where(AuditEvent.tenant_id == TENANT_A)).action == (
        "provider.credential.created"
    )


def test_provider_secret_cannot_be_read_from_another_tenant(session: Session) -> None:
    credential = create_provider_credential(
        session,
        vault=vault(),
        tenant_id=TENANT_A,
        provider_id="openai",
        label="primary",
        plaintext_secret="sk-live-test",
        created_by="user-1",
        request_id="req-create",
    )
    session.commit()

    with pytest.raises(HTTPException) as error:
        get_provider_secret(
            session, vault=vault(), tenant_id=TENANT_B, credential_id=credential.id
        )
    assert error.value.status_code == 404


def test_revocation_erases_ciphertext_and_appends_audit_event(session: Session) -> None:
    credential = create_provider_credential(
        session,
        vault=vault(),
        tenant_id=TENANT_A,
        provider_id="anthropic",
        label="primary",
        plaintext_secret="secret",
        created_by="user-1",
        request_id="req-create",
    )
    session.commit()

    revoke_provider_credential(
        session,
        tenant_id=TENANT_A,
        credential_id=credential.id,
        actor_subject="user-1",
        request_id="req-revoke",
    )
    session.commit()

    stored = session.scalar(
        select(ProviderCredential).where(ProviderCredential.id == credential.id)
    )
    assert stored is not None
    assert stored.revoked_at is not None
    assert stored.encrypted_secret == b""
    assert stored.nonce == bytes(12)
    with pytest.raises(HTTPException) as error:
        get_provider_secret(
            session, vault=vault(), tenant_id=TENANT_A, credential_id=credential.id
        )
    assert error.value.status_code == 404
    assert verify_audit_chain(session, tenant_id=TENANT_A)


def test_provider_credential_rejects_unknown_provider(session: Session) -> None:
    with pytest.raises(ValueError, match="not supported"):
        create_provider_credential(
            session,
            vault=vault(),
            tenant_id=TENANT_A,
            provider_id="unknown",
            label="primary",
            plaintext_secret="secret",
            created_by="user-1",
            request_id="req",
        )
