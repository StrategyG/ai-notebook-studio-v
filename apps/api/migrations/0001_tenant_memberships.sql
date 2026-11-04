-- Apply with a migration role. Runtime application role must not own these tables,
-- must not have BYPASSRLS, and must not be a PostgreSQL superuser.
CREATE TABLE IF NOT EXISTS tenant_memberships (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    subject varchar(255) NOT NULL,
    role varchar(64) NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'suspended', 'revoked')),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_tenant_memberships_tenant_subject UNIQUE (tenant_id, subject)
);

CREATE INDEX IF NOT EXISTS ix_tenant_memberships_tenant_id
    ON tenant_memberships (tenant_id);

ALTER TABLE tenant_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_memberships FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_memberships_isolation ON tenant_memberships;
CREATE POLICY tenant_memberships_isolation ON tenant_memberships
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
