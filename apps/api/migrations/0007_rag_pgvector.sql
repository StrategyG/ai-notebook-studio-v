-- Tenant-isolated RAG storage. Embeddings use the fixed 1536-dimensional
-- profile configured by EMBEDDING_DIMENSIONS and the API runtime.
BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

DO $pgvector_version_check$
DECLARE
    installed_version text;
BEGIN
    SELECT extversion INTO installed_version
    FROM pg_extension
    WHERE extname = 'vector';

    IF installed_version IS NULL
       OR string_to_array(installed_version, '.')::integer[] < ARRAY[0, 8, 0]::integer[] THEN
        RAISE EXCEPTION 'pgvector >= 0.8.0 is required for filtered iterative HNSW scans (found %)',
            COALESCE(installed_version, 'not installed');
    END IF;
END;
$pgvector_version_check$;

CREATE TABLE IF NOT EXISTS rag_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    title varchar(512) NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 512),
    source_uri varchar(2048) NOT NULL CHECK (length(btrim(source_uri)) BETWEEN 1 AND 2048),
    source_type varchar(32) NOT NULL
        CHECK (source_type IN ('url', 'upload', 'manual', 'repository')),
    embedding_model varchar(128) NOT NULL DEFAULT 'legacy-unmapped'
        CHECK (length(btrim(embedding_model)) BETWEEN 1 AND 128),
    content text NOT NULL CHECK (length(content) BETWEEN 1 AND 1000000),
    content_sha256 varchar(64) NOT NULL CHECK (content_sha256 ~ '^[a-f0-9]{64}$'),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_by varchar(255) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_rag_documents_tenant_source_hash_model
        UNIQUE (tenant_id, source_uri, content_sha256, embedding_model),
    CONSTRAINT uq_rag_documents_id_tenant UNIQUE (id, tenant_id)
);

CREATE TABLE IF NOT EXISTS rag_document_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    document_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    content text NOT NULL CHECK (length(content) > 0),
    start_char integer NOT NULL CHECK (start_char >= 0),
    end_char integer NOT NULL CHECK (end_char > start_char),
    content_sha256 varchar(64) NOT NULL CHECK (content_sha256 ~ '^[a-f0-9]{64}$'),
    embedding vector(1536) NOT NULL,
    search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_rag_chunks_document_tenant
        FOREIGN KEY (document_id, tenant_id)
        REFERENCES rag_documents (id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT uq_rag_chunks_document_ordinal UNIQUE (document_id, ordinal)
);

CREATE INDEX IF NOT EXISTS ix_rag_documents_tenant_created
    ON rag_documents (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_rag_documents_metadata_gin
    ON rag_documents USING gin (metadata jsonb_path_ops);

CREATE INDEX IF NOT EXISTS ix_rag_chunks_tenant_document
    ON rag_document_chunks (tenant_id, document_id);

CREATE INDEX IF NOT EXISTS ix_rag_chunks_search_tsv
    ON rag_document_chunks USING gin (search_tsv);

CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_hnsw
    ON rag_document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

ALTER TABLE rag_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag_documents FORCE ROW LEVEL SECURITY;
ALTER TABLE rag_document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag_document_chunks FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS rag_documents_tenant_isolation ON rag_documents;
CREATE POLICY rag_documents_tenant_isolation ON rag_documents
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS rag_document_chunks_tenant_isolation ON rag_document_chunks;
CREATE POLICY rag_document_chunks_tenant_isolation ON rag_document_chunks
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

REVOKE ALL ON TABLE rag_documents, rag_document_chunks FROM PUBLIC;

COMMIT;
