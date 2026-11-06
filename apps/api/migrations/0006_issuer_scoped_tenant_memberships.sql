-- Preserve the verified OIDC issuer in the canonical API membership identity.
-- Legacy rows stay issuer=NULL and do not authorize runtime access until an operator
-- verifies their provenance and performs an explicit backfill.
ALTER TABLE tenant_memberships
    ADD COLUMN IF NOT EXISTS issuer varchar(2048);

ALTER TABLE tenant_memberships
    DROP CONSTRAINT IF EXISTS uq_tenant_memberships_tenant_subject;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_memberships_tenant_issuer_subject
    ON tenant_memberships (tenant_id, issuer, subject);

COMMENT ON COLUMN tenant_memberships.issuer IS
    'Verified OIDC issuer. NULL is legacy/unmapped and never authorizes runtime access.';
