from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_notebook_api.db.models import ProviderCredential
from ai_notebook_api.db.session import apply_tenant_database_context
from ai_notebook_api.security.vault import EncryptedSecret, SecretVault, VaultDecryptionError
from ai_notebook_api.services.audit import append_audit_event

SUPPORTED_PROVIDER_IDS = frozenset({"openai", "anthropic", "google", "azure-openai"})


def create_provider_credential(
    session: Session,
    *,
    vault: SecretVault,
    tenant_id: UUID,
    provider_id: str,
    label: str,
    plaintext_secret: str,
    created_by: str,
    request_id: str,
) -> ProviderCredential:
    if provider_id not in SUPPORTED_PROVIDER_IDS:
        raise ValueError("provider id is not supported")
    if not label or len(label) > 64 or not label.strip():
        raise ValueError("credential label must be 1..64 characters")
    if not created_by or len(created_by) > 255 or not request_id or len(request_id) > 128:
        raise ValueError("credential actor and request identifiers are required")

    apply_tenant_database_context(session, str(tenant_id))
    credential_id = uuid4()
    encrypted = vault.encrypt(
        plaintext_secret,
        tenant_id=tenant_id,
        credential_id=credential_id,
        provider_id=provider_id,
    )
    credential = ProviderCredential(
        id=credential_id,
        tenant_id=tenant_id,
        provider_id=provider_id,
        label=label,
        key_id=encrypted.key_id,
        nonce=encrypted.nonce,
        encrypted_secret=encrypted.ciphertext,
        created_by=created_by,
    )
    session.add(credential)
    session.flush()
    append_audit_event(
        session,
        tenant_id=tenant_id,
        actor_subject=created_by,
        action="provider.credential.created",
        resource_type="provider_credential",
        resource_id=str(credential_id),
        request_id=request_id,
        payload={"provider_id": provider_id, "label": label},
    )
    return credential


def get_provider_secret(
    session: Session,
    *,
    vault: SecretVault,
    tenant_id: UUID,
    credential_id: UUID,
) -> str:
    apply_tenant_database_context(session, str(tenant_id))
    credential = session.scalar(
        select(ProviderCredential).where(
            ProviderCredential.id == credential_id,
            ProviderCredential.tenant_id == tenant_id,
            ProviderCredential.revoked_at.is_(None),
        )
    )
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider credential not found",
        )
    try:
        return vault.decrypt(
            EncryptedSecret(
                key_id=credential.key_id,
                nonce=credential.nonce,
                ciphertext=credential.encrypted_secret,
            ),
            tenant_id=tenant_id,
            credential_id=credential.id,
            provider_id=credential.provider_id,
        )
    except VaultDecryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Provider credential cannot be decrypted by this deployment",
        ) from exc


def revoke_provider_credential(
    session: Session,
    *,
    tenant_id: UUID,
    credential_id: UUID,
    actor_subject: str,
    request_id: str,
) -> None:
    apply_tenant_database_context(session, str(tenant_id))
    credential = session.scalar(
        select(ProviderCredential)
        .where(
            ProviderCredential.id == credential_id,
            ProviderCredential.tenant_id == tenant_id,
            ProviderCredential.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider credential not found",
        )
    credential.revoked_at = datetime.now(UTC)
    credential.encrypted_secret = b""
    credential.nonce = bytes(12)
    append_audit_event(
        session,
        tenant_id=tenant_id,
        actor_subject=actor_subject,
        action="provider.credential.revoked",
        resource_type="provider_credential",
        resource_id=str(credential_id),
        request_id=request_id,
        payload={"provider_id": credential.provider_id, "label": credential.label},
    )
    session.flush()
