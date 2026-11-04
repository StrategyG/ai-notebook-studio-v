-- Enforce the API membership role vocabulary for all new and modified rows.
-- NOT VALID keeps this migration safe for deployments that may contain legacy values;
-- existing rows must be audited and repaired before the constraint is validated.
--
-- Preflight / validation runbook:
--   SELECT role, count(*) FROM tenant_memberships GROUP BY role ORDER BY role;
--   -- Correct any non-canonical values through an approved data migration.
--   ALTER TABLE tenant_memberships VALIDATE CONSTRAINT ck_tenant_memberships_role;
--
-- Supabase public.tenant_memberships has a separate role vocabulary and must not
-- be copied into this API database without an explicit identity/role mapping contract.
ALTER TABLE tenant_memberships
    ADD CONSTRAINT ck_tenant_memberships_role
    CHECK (role IN ('owner', 'admin', 'editor', 'member', 'viewer'))
    NOT VALID;
