-- Add issuer-scoped external identity to API tenant memberships.
-- Existing rows remain issuer=NULL until an operator verifies their identity-provider
-- provenance and performs an explicit backfill. NULL issuer rows cannot authorize
-- requests because runtime membership resolution requires an exact issuer match.
--
-- Before validating/backfilling legacy rows, inventory every identity provider and
-- reconcile (issuer, subject) against its authoritative directory. Never infer issuer
-- from email, JWT roles, or subject alone.
ALTER TABLE tenant_memberships
    ADD COLUMN IF NOT EXISTS issuer varchar(2048);

-- Replace subject-only uniqueness with the actual OIDC principal identity.
-- PostgreSQL permits multiple NULL issuer values, intentionally isolating legacy rows
-- from issuer-scoped authorization until their provenance is verified.
ALTER TABLE tenant_memberships
    DROP CONSTRAINT IF EXISTS uq_tenant_memberships_tenant_subject;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_memberships_tenant_issuer_subject
    ON tenant_memberships (tenant_id, issuer, subject);

COMMENT ON COLUMN tenant_memberships.issuer IS
    'OIDC issuer for this membership. NULL is legacy/unmapped and never authorizes runtime access.';
