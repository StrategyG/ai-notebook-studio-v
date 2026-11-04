# V6 BYOK Credential Vault

## Implemented

- AES-256-GCM authenticated encryption for provider credentials.
- Per-credential random 96-bit nonce and authenticated associated data binding ciphertext to tenant, credential ID and provider.
- Deployment-injected versioned keyring via `PROVIDER_VAULT_KEYS` and `PROVIDER_VAULT_ACTIVE_KEY_ID`.
- Rotation support: old key IDs remain decryptable while new writes use the active key ID.
- Tenant-scoped credential records protected by PostgreSQL RLS.
- Plaintext is returned only to trusted server-side service code; no API response returns credential values.
- Credential creation and revocation append audit events in the same transaction.
- Revocation clears stored ciphertext and overwrites the nonce while preserving the schema's nonce-length invariant.
- Tests cover encryption, tenant-bound AAD, tamper detection, key rotation, storage, access denial and revocation.

## Deployment key handling

- Generate independent random 32-byte keys for each key ID and encode each with URL-safe base64.
- Inject the JSON keyring and active key ID through a secrets manager or KMS-backed deployment secret integration.
- Never commit key material, place it in the Android client, expose it through API responses, or log it.
- During rotation, deploy old and new keys together, switch the active key ID, then re-encrypt existing credentials under the new key in a separately controlled rotation job before removing old keys.

## Limitations

- This increment does not connect to a live cloud KMS or secrets manager; key delivery is an environment contract.
- No provider request adapter, model routing, budget enforcement, streaming or live provider call is implemented yet.
- A production deployment still needs key rotation automation, backup/restore testing and independent secret-management review.
