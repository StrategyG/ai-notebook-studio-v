# RAG and MCP production implementation

## Scope

This branch adds a tenant-scoped PostgreSQL RAG path and a separately authenticated MCP Streamable HTTP resource server.

The API ingests extracted UTF-8 text and provides a bounded multipart upload route for PDF, DOCX, HTML, Markdown, and UTF-8 TXT. Upload parsing is size-limited and does not execute embedded content. The RAG service does not persist original binary files; it records the raw-file SHA-256, filename, parser, and media type alongside the extracted text. Starlette may temporarily spool multipart data, so production must provide an isolated, size-bounded temporary directory with appropriate filesystem protections and cleanup. The API does not fetch arbitrary URLs; a URL source URI is provenance for already-extracted text, not an instruction to crawl the network.

## Components

- PostgreSQL stores original document text, source digest, metadata, embedding model identity, chunks, offsets, and vectors.
- pgvector >= 0.8.0 uses a fixed 1536-dimensional vector profile with a cosine HNSW index. Retrieval enables strict-order iterative scans and a bounded ef_search setting so tenant and metadata filters do not prematurely underfill approximate-nearest-neighbor candidate lists.
- PostgreSQL GIN full-text index supports lexical candidates.
- Hybrid retrieval combines vector and lexical ranks using Reciprocal Rank Fusion (RRF).
- Metadata filtering uses parameterized JSONB containment and is always combined with the authenticated tenant predicate.
- RLS is enabled and forced on both RAG tables. Composite (document_id, tenant_id) foreign keys prevent cross-tenant chunk ownership.
- Citations include document/chunk IDs, source URI, source and chunk SHA-256 digests, and exact character offsets. The citation-source endpoint recomputes hashes and checks that the original text slice equals the cited excerpt.
- MCP exposes only rag_search and rag_get_document. The MCP HTTP resource server validates JWT/JWKS identity and the mcp:tools:call scope at the transport boundary; each tool also checks its own narrow scope and database-backed tenant role.

## API

All routes require a verified bearer token and an active membership matching the exact (tenant_id, issuer, subject) tuple.

| Method | Route | Permission | Purpose |
|---|---|---|---|
| POST | /api/v1/rag/documents | documents:write | Index extracted document text |
| POST | /api/v1/rag/documents/upload | documents:write | Parse and index a bounded supported file upload |
| POST | /api/v1/rag/search | rag:search | Hybrid semantic + lexical retrieval |
| GET | /api/v1/rag/documents/{document_id} | documents:read | Read a tenant-owned source |
| GET | /api/v1/rag/documents/{document_id}/chunks/{chunk_id} | documents:read | Verify citation provenance |

Example ingestion request:

~~~json
{
  "title": "Security policy",
  "source_uri": "https://docs.example.org/security-policy",
  "source_type": "url",
  "content": "Extracted UTF-8 source text goes here.",
  "metadata": {
    "department": "security",
    "classification": "internal"
  }
}
~~~

Example retrieval request:

~~~json
{
  "query": "How is tenant isolation enforced?",
  "limit": 5,
  "metadata_filter": {
    "department": "security"
  }
}
~~~

The upload endpoint enforces a streaming multipart request ceiling of 10 MB plus bounded multipart overhead before form parsing, accepts files up to 10 MB, caps extracted text at 1 million characters, limits PDFs to 500 pages, and bounds DOCX archive entries and uncompressed size. source_type=url records the origin of already-extracted text. It does not cause the API to fetch the URL. URL fetching, if later required, must be implemented as a separate SSRF-hardened ingestion worker with DNS/IP validation, redirect restrictions, response-size limits, and content-type allowlisting.

## Required configuration

Set secrets through the deployment secret manager. Never commit values to .env, workflow YAML, source code, logs, or prompts.

| Variable | Required | Notes |
|---|---:|---|
| DATABASE_URL | Yes | PostgreSQL runtime role; must be NOSUPERUSER NOBYPASSRLS; staging/production require sslmode=verify-full |
| RAG_ENABLED | Yes | true to enable RAG routes |
| EMBEDDING_API_URL | Yes | HTTPS OpenAI-compatible /embeddings endpoint in production |
| EMBEDDING_API_KEY | Yes | Secret-manager value; never logged |
| EMBEDDING_MODEL | Yes | Must be the same model used for ingestion and query |
| EMBEDDING_DIMENSIONS | Yes | Must be 1536 for migration 0007 |
| EMBEDDING_TIMEOUT_SECONDS | No | Default 30; accepted range 1–120 |
| AUTH_JWKS_URL | Yes | HTTPS JWKS endpoint |
| AUTH_ISSUER | Yes | Exact HTTPS OIDC issuer |
| AUTH_AUDIENCE | Yes | API audience validated in the JWT |
| AUTH_ALGORITHMS | No | Allowlisted RS256 or ES256; default RS256 |
| MCP_ENABLED | No | false unless MCP is intentionally exposed |
| MCP_RESOURCE_SERVER_URL | MCP | Public HTTPS URL ending in /mcp |
| MCP_ALLOWED_HOSTS | MCP | Exact host entries including default-port variants, e.g. mcp.example.org,mcp.example.org:443,mcp.example.org:* |
| MCP_ALLOWED_ORIGINS | MCP | Explicit HTTPS browser origins; may be empty for non-browser clients |

MCP must remain disabled until the resource URL, host allowlist, issuer/JWKS, audience, PostgreSQL role, and embedding provider are all configured. An incomplete enabled configuration intentionally prevents startup.

## Database migration and role requirements

Apply migrations in lexical order using the privileged migration identity:

1. Existing platform migrations 0001–0005.
2. 0006_issuer_scoped_tenant_memberships.sql.
3. 0007_rag_pgvector.sql.

Migration 0006 adds the OIDC issuer to the API membership identity. Legacy rows remain issuer IS NULL and **do not authorize**. Backfill them only after independently verifying the identity provider that issued each subject. Do not bulk-copy issuer values from an untrusted claim or from another tenant database.

Migration 0007 installs pgvector, creates RAG document/chunk tables and indexes, and enables FORCE ROW LEVEL SECURITY. The legacy-unmapped embedding model default exists only for migration/test compatibility; the application always writes the configured model name and never retrieves legacy vectors as if they belonged to that model.

The API runtime role must:
- Be a non-superuser and have NOBYPASSRLS.
- Not own the RAG tables.
- Have only the table privileges required by the deployed API.
- Use transaction-local app.tenant_id context set after identity and membership validation.
- Connect with sslmode=verify-full in staging and production, and use a bounded connection pool.

Do not use the migration owner, PostgreSQL superuser, or a role with BYPASSRLS as DATABASE_URL.

## Retrieval evaluation

The versioned fixture is tests/evaluation/rag_retrieval.json. It contains a small curated corpus and 12 labeled queries. It is a deterministic engineering acceptance set, not a substitute for a production-domain benchmark. Before production sign-off, add representative, human-reviewed queries and relevant-source labels from each document domain and tenant workflow.

Run:

~~~bash
cd apps/api
RAG_ENABLED=true \
DATABASE_URL="$RAG_EVAL_DATABASE_URL" \
EMBEDDING_API_URL="https://embedding.example/v1/embeddings" \
EMBEDDING_API_KEY="$EMBEDDING_API_KEY" \
EMBEDDING_MODEL="text-embedding-3-small" \
EMBEDDING_DIMENSIONS=1536 \
python scripts/evaluate_rag.py
~~~

The evaluator:
- Uses the real configured embedding endpoint; it does not generate mock vectors.
- Precomputes vectors before opening a database transaction.
- Creates an isolated random tenant namespace for each run.
- Refuses to run as a superuser or BYPASSRLS role.
- Verifies relrowsecurity and relforcerowsecurity on both RAG tables.
- Rolls back fixture writes after evaluation.
- Recomputes every returned citation's source hash, chunk hash, and character offsets.

Acceptance targets:

| Metric | Minimum |
|---|---:|
| Recall@5 | 0.90 |
| MRR@10 | 0.80 |
| nDCG@10 | 0.85 |
| Citation integrity | 1.00 |
| Cross-tenant retrieval leakage | 0 |

The first four targets are evaluated by the versioned retrieval script. The zero-leakage target is separately enforced by PostgreSQL integration tests that attempt cross-tenant reads, updates, deletes, and inserts using the restricted runtime role. A passing fixture benchmark alone does not prove production-domain relevance.

Run the real-provider evaluation manually through the **RAG Live Retrieval Evaluation** GitHub Actions workflow after configuring the protected rag-evaluation environment secrets.

## Operational acceptance gates

Do not mark this module production-ready until all of the following are evidenced:

- Migrations apply to a clean PostgreSQL 16 + pgvector database and to a representative upgrade snapshot.
- Runtime role is verified as NOSUPERUSER NOBYPASSRLS.
- RLS integration tests pass for read, insert, update, and delete attempts across tenants.
- Ingestion, idempotent re-ingestion, metadata filtering, vector search, lexical search, and RRF are exercised against PostgreSQL.
- The real embedding provider returns the configured dimension and passes the live evaluation target.
- Citation provenance checks pass for every retrieved citation.
- MCP HTTP requests without valid bearer tokens are rejected; wrong issuer, audience, expiry, tenant, role, or scope cannot invoke a tool.
- MCP tool listing contains only the reviewed allowlist.
- API and PostgreSQL tests pass in CI with the configured coverage gate.
- Production secrets, TLS, database backups, migration rollback/restore procedure, monitoring, rate limits, and resource limits are configured by the deployment owner.

This branch deliberately leaves the platform metadata production_ready flag false until the end-to-end deployment and operational gates above have passed.
