# V6 Durable Audit Ledger

## Implemented

- Tenant-scoped append-only audit event model.
- Per-tenant monotonic sequence number and SHA-256 hash chain.
- Canonical JSON serialization with stable key ordering.
- PostgreSQL transaction advisory lock to serialize concurrent appends within one tenant.
- Verification function that detects sequence gaps, previous-hash mismatches and payload/hash tampering.
- PostgreSQL RLS policy and forced row-level security for audit records.
- PostgreSQL trigger rejects UPDATE and DELETE.
- The audit append service leaves transaction commit to the caller so the business operation and audit event can be committed atomically.

## Operational requirements

- The migration role owns the table and trigger. The application role must not own the table, be superuser, or have BYPASSRLS.
- Grant the runtime role SELECT and INSERT only; do not grant UPDATE or DELETE.
- Do not log access tokens, provider keys, raw notebook contents, or other secrets in audit payloads. Store references and bounded metadata.
- Call the audit append function in the same database transaction as the business state change.
- Export/replicate the ledger to separately controlled immutable storage for stronger tamper resistance. A hash chain alone does not protect against a privileged database administrator rewriting the full chain.

## Limitations

- This is a service/model foundation; business write endpoints are not yet wired to it.
- External immutable archival, key-managed signatures, retention controls and alerting are not implemented.
- PostgreSQL trigger and privilege behavior must be exercised in CI with the restricted runtime role before production use.
