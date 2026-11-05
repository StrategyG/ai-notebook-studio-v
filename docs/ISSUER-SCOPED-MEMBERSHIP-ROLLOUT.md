# Issuer-scoped tenant membership rollout

**Status:** operator runbook for PR #20; not an executed migration or data backfill.

## Security invariant

A tenant membership is authorized only by the exact tuple:

`(tenant_id, issuer, subject)`

The JWT must have a verified signature and the configured issuer. The API must never infer issuer from email, `sub`, a role claim, a tenant name, or a Supabase UUID.

Rows with `issuer IS NULL` are legacy/unmapped records. The API resolver intentionally does not authorize them.

## Preconditions

- Review and merge the issuer-scoped code and migration through the normal PR process.
- Confirm the migration target, backup freshness, restore procedure and maintenance window.
- Obtain an authoritative identity-provider export or mapping approved by the tenant identity owner. It must contain the exact issuer and opaque subject for each membership; record a non-secret provenance reference for each mapping.
- Use a privileged migration operator connection for this procedure. Never use the application runtime role, an exposed Data API role, or a worker credential.
- Test the complete procedure on a production-like staging clone first.

## Phase 1 — schema rollout

Apply `apps/api/migrations/0006_issuer_scoped_tenant_memberships.sql` using the approved migration runner.

The migration:
- Adds nullable `issuer`.
- Removes subject-only uniqueness.
- Adds uniqueness for `(tenant_id, issuer, subject)`.
- Does not assign an issuer to existing records.

Do not run the application against production until the identity owner understands that legacy NULL-issuer memberships will fail closed.

## Phase 2 — prepare and validate the mapping

Load a protected, short-lived mapping into a temporary table using the migration operator connection. Do not commit the export or mapping file to Git.

Example shape:

```sql
CREATE TEMP TABLE verified_membership_issuer_map (
    tenant_id uuid NOT NULL,
    subject varchar(255) NOT NULL,
    issuer varchar(2048) NOT NULL,
    provenance_ref text NOT NULL,
    PRIMARY KEY (tenant_id, subject)
) ON COMMIT PRESERVE ROWS;
```

Populate it only from the authoritative identity-provider export. Before updating memberships, reject rows whose issuer is not an absolute HTTPS issuer:

```sql
SELECT tenant_id, subject
FROM verified_membership_issuer_map
WHERE issuer !~ '^https://[^?#]+$';
```

The result must be empty. Verify that every currently active legacy membership has exactly one mapping:

```sql
SELECT m.tenant_id, m.subject
FROM tenant_memberships AS m
LEFT JOIN verified_membership_issuer_map AS x
  ON x.tenant_id = m.tenant_id
 AND x.subject = m.subject
WHERE m.status = 'active'
  AND m.issuer IS NULL
  AND x.subject IS NULL;
```

The result must be empty before the backfill is approved. Investigate any ambiguous or unmatched identity manually; do not guess.

## Phase 3 — explicit backfill

Within a reviewed transaction, update only legacy rows matched by the verified mapping:

```sql
BEGIN;

UPDATE tenant_memberships AS m
SET issuer = x.issuer
FROM verified_membership_issuer_map AS x
WHERE m.tenant_id = x.tenant_id
  AND m.subject = x.subject
  AND m.issuer IS NULL;

-- Stop and ROLLBACK if either query returns a non-zero count.
SELECT count(*) AS active_memberships_without_issuer
FROM tenant_memberships
WHERE status = 'active'
  AND issuer IS NULL;

SELECT tenant_id, issuer, subject, count(*) AS duplicate_count
FROM tenant_memberships
WHERE issuer IS NOT NULL
GROUP BY tenant_id, issuer, subject
HAVING count(*) > 1;

COMMIT;
```

The application must remain blocked for unresolved active rows. Record before/after counts, mapping provenance identifier, migration checksum, operator identity, timestamp and database snapshot/backup identifier in the controlled evidence ledger. Do not put the mapping export or personal identity data in the ledger.

## Phase 4 — verification

- Test a real signed token from the configured issuer against the exact membership tuple.
- Test that the same `subject` from a different issuer is denied.
- Test that a NULL-issuer legacy row is denied.
- Test tenant isolation with two tenants and at least two principals.
- Verify that role and membership status are still sourced from the database, not token claims.
- Verify login, workspace access, task authorization and audit behavior in staging.
- Capture exact commit SHA, migration checksum, test artifacts and independent reviewer identity.

## Rollback and recovery

Do **not** roll back to subject-only authorization or recreate the old `(tenant_id, subject)` uniqueness rule; that would reintroduce cross-issuer identity ambiguity.

If the backfill or verification fails:
1. Stop the application rollout or disable the affected API traffic.
2. Keep the issuer-scoped schema and fail-closed resolver.
3. Restore from the verified backup only under the approved recovery procedure if the data itself was corrupted.
4. Reconcile ambiguous memberships from the authoritative identity provider and rerun the checks.

A future migration to make `issuer NOT NULL` is intentionally separate. It may be proposed only after the active and required historical membership population is fully reconciled and independently verified.

## Release gate

This runbook is complete only when the schema is applied in staging, all required memberships are explicitly mapped, the NULL and duplicate checks return zero, tenant/issuer negative tests pass, backup/restore is verified, and the release evidence is reviewed. Creating this document does not mean any of those operational steps have been performed.
