CREATE TABLE IF NOT EXISTS provider_credentials (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    provider_id varchar(64) NOT NULL,
    label varchar(64) NOT NULL,
    key_id varchar(64) NOT NULL,
    nonce bytea NOT NULL CHECK (octet_length(nonce) = 12),
    encrypted_secret bytea NOT NULL,
    created_by varchar(255) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    CONSTRAINT uq_provider_credentials_tenant_provider_label
        UNIQUE (tenant_id, provider_id, label)
);

CREATE INDEX IF NOT EXISTS ix_provider_credentials_tenant_id
    ON provider_credentials (tenant_id);

ALTER TABLE provider_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE provider_credentials FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS provider_credentials_tenant_isolation ON provider_credentials;
CREATE POLICY provider_credentials_tenant_isolation ON provider_credentials
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
