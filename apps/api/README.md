# AI Notebook Studio API — V6 modular backend

This package is an incremental modular-monolith API foundation. It contains verified OIDC/JWKS identity, database-backed issuer-scoped tenant membership, tenant authorization, PostgreSQL persistence, and a tenant-scoped RAG retrieval backend. The RAG increment also provides an authenticated Streamable HTTP MCP resource server when explicitly enabled.

This repository increment is **not a production approval**. Production remains NO-GO until the complete system acceptance plan, live staging evaluation, security review, and deployment/recovery gates pass.

## Local development

~~~bash
python -m pip install -e '.[dev]'
PYTHONPATH=src pytest
uvicorn ai_notebook_api.main:app --app-dir src --reload
~~~

Copy `.env.example` into the local secret/configuration mechanism. Do not commit real tokens, database passwords, or embedding keys.

## Identity and tenant authorization

Configure:

- `AUTH_JWKS_URL`: HTTPS JWKS endpoint.
- `AUTH_ISSUER`: exact HTTPS OIDC issuer.
- `AUTH_AUDIENCE`: expected API audience.
- `AUTH_ALGORITHMS`: signing algorithm allowlist (RS256 or ES256).

The verifier validates signature, issuer, audience, expiry, subject, and UUID `tenant_id`. Active tenant membership is resolved by the exact `(tenant_id, issuer, subject)` tuple. Roles are read from PostgreSQL, not trusted from caller-supplied request data. Legacy memberships with a NULL issuer do not authorize requests.

## PostgreSQL migrations and runtime role

Apply SQL migrations in lexical order using a dedicated migration role:

1. `migrations/0001_tenant_memberships.sql`
2. `migrations/0002_audit_events.sql`
3. `migrations/0003_outbox_events.sql`
4. `migrations/0004_provider_credentials.sql`
5. `migrations/0005_tenant_membership_role_constraint.sql`
6. `migrations/0006_issuer_scoped_tenant_memberships.sql`
7. `migrations/0007_rag_pgvector.sql`

The RAG migration installs pgvector, creates 1536-dimensional document embeddings, a cosine HNSW index, a GIN full-text index, composite tenant/document foreign keys, and forced tenant RLS. The application runtime role must be a non-superuser, must not have `BYPASSRLS`, and must not own tenant tables.

Grant only the privileges required by enabled features. For RAG retrieval and ingestion:

~~~sql
GRANT USAGE ON SCHEMA public TO app_runtime;
GRANT SELECT, INSERT ON rag_documents, rag_document_chunks TO app_runtime;
~~~

The migration role, database owner, and runtime API role must be separate. Never expose database credentials to the browser.

## RAG API

Enable the real embedding provider:

~~~bash
RAG_ENABLED=true
EMBEDDING_API_URL=https://embedding.internal.example/v1/embeddings
EMBEDDING_API_KEY=<secret-from-secret-manager>
EMBEDDING_MODEL=<deployed-embedding-model>
EMBEDDING_DIMENSIONS=1536
EMBEDDING_TIMEOUT_SECONDS=30
~~~

The provider must implement the OpenAI-compatible embeddings response contract with `data[].index` and `data[].embedding`. The adapter checks response count/order, dimension, numeric values, and finite floats. It does not fabricate embeddings or silently fall back to lexical-only search.

Available endpoints (all require a verified bearer token and active tenant membership):

| Method | Route | Permission |
|---|---|---|
| POST | `/api/v1/rag/documents` | `documents:write` |
| POST | `/api/v1/rag/documents/upload` | `documents:write` |
| POST | `/api/v1/rag/search` | `rag:search` |
| GET | `/api/v1/rag/documents/{document_id}` | `documents:read` |
| GET | `/api/v1/rag/documents/{document_id}/chunks/{chunk_id}` | `documents:read` |

The text ingestion route accepts extracted text and a stable source URI. A separate multipart upload route accepts PDF, DOCX, HTML, Markdown, and UTF-8 TXT files. Uploads are limited to 10 MB raw bytes, 1 MB extracted characters, 500 PDF pages, 512 DOCX archive entries, and 30 MB uncompressed DOCX content. The parser does not execute embedded content, fetch remote links, or write uploads to disk. Spreadsheet parsing, OCR, remote URL fetching, generated answers, and reranking remain outside this increment. See [RAG and MCP implementation notes](../../docs/RAG-MCP-V1.md).

Search combines pgvector cosine-nearest-neighbor candidates and PostgreSQL full-text candidates with reciprocal rank fusion. Metadata filtering uses parameterized JSONB containment and does not replace tenant predicates. Citations include document/chunk IDs, source URI, embedding model, SHA-256 digests, and exact character offsets. The citation verification endpoint recomputes hashes and checks the excerpt against the stored source slice.

## MCP resource server

Enable only when the API, database, identity provider, and embedding provider are configured:

~~~bash
MCP_ENABLED=true
MCP_RESOURCE_SERVER_URL=https://api.example.com/mcp
MCP_ALLOWED_HOSTS=api.example.com,api.example.com:443,api.example.com:*
MCP_ALLOWED_ORIGINS=https://trusted-mcp-client.example
~~~

The server exposes exactly two read-only tools:

- `rag_search(query, limit, metadata_filter)`
- `rag_get_document(document_id)`

Every tool call verifies the bearer token, required scopes, issuer-scoped active membership, and database-backed role permissions. The endpoint is stateless Streamable HTTP with JSON responses and a 1 MiB request-body limit. Host allowlisting is mandatory. When MCP is disabled, `/mcp` returns 503; invalid enabled configuration fails closed.

## Tests and retrieval evaluation

Run the API tests and lint:

~~~bash
ruff check src tests scripts
pytest --cov=ai_notebook_api --cov-report=term-missing
~~~

The Python API CI provisions PostgreSQL with pgvector, runs migrations under a migration role, creates a restricted `NOBYPASSRLS` runtime role, and runs forced-RLS and hybrid retrieval integration tests.

The versioned retrieval dataset is `tests/evaluation/rag_retrieval.json` (12 documents and 12 queries). For a live evaluation against the configured embedding endpoint and PostgreSQL, run the **RAG Live Retrieval Evaluation** GitHub Actions workflow. Configure these in the protected GitHub `staging` environment:

- Secret `RAG_EVAL_DATABASE_URL`: PostgreSQL URL for a restricted non-superuser role with `NOBYPASSRLS`.
- Secret `EMBEDDING_API_URL`.
- Secret `EMBEDDING_API_KEY`.
- Repository variable `EMBEDDING_MODEL`.

Each run creates a unique evaluation tenant namespace and rolls back fixture writes after measuring retrieval. Required targets:

| Metric | Minimum |
|---|---:|
| Recall@5 | 0.90 |
| MRR@10 | 0.80 |
| NDCG@10 | 0.85 |
| Citation integrity rate | 1.00 |
| Citation integrity | 1.00 |

A failed metric exits non-zero. The small pinned dataset is a regression baseline; before release, supplement it with a representative, reviewed corpus and queries from the intended deployment domain.

## Readiness and release boundary

- `/health/live` reports process liveness.
- `/health/ready` checks database connectivity, required schema, OIDC/JWKS reachability, and enabled RAG/MCP configuration. It does not replace live retrieval evaluation or tenant-isolation tests.
- The full release decision remains NO-GO until all acceptance-plan items, including live staging retrieval, public MCP interoperability, cross-tenant negative tests, and production operational controls, have verified evidence.
