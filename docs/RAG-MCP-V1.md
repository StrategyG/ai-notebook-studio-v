# Tenant-scoped RAG and MCP v1

## Scope

This increment adds a retrieval backend, not a text-generation endpoint. It ingests text supplied by an authenticated caller or extracts text from bounded PDF, DOCX, HTML, Markdown, and UTF-8 TXT uploads. It stores the original extracted source and chunk embeddings in PostgreSQL, then returns hybrid-ranked passages with verifiable provenance. The MCP server exposes only the read-only retrieval tools listed below.

Spreadsheet parsing, OCR, remote URL fetching, answer generation, and reranking are not part of this increment. The system never follows source links as part of ingestion.

## Data and retrieval flow

1. The API verifies the JWT signature, issuer, audience, expiry, and required claims.
2. It resolves an active membership by (tenant_id, issuer, subject) and reads the role from PostgreSQL.
3. The tenant ID is set transaction-locally in app.tenant_id; RLS is the final database boundary.
4. The upload endpoint enforces a 10 MiB raw-file limit, parses PDF/DOCX/HTML/Markdown/TXT without executing embedded content or fetching remote URLs, records the uploaded file SHA-256 and parser metadata, and passes extracted text to ingestion. The direct-text endpoint validates source URI and bounded JSON metadata. Both hash extracted source text, chunk it with deterministic character offsets, and call the configured OpenAI-compatible embedding endpoint.
5. Every chunk stores its source document ID, ordinal, exact offsets, SHA-256 digest, and 1536-dimensional vector.
6. Search retrieves vector candidates with pgvector cosine distance and lexical candidates with PostgreSQL full-text search. Reciprocal rank fusion combines the two ranked lists.
7. Search results include source URI, document and chunk hashes, and character offsets. The citation-source endpoint recomputes both hashes and checks that the cited excerpt equals the source slice.

Re-ingesting the same (tenant_id, source_uri, content_sha256, embedding_model) is idempotent, including concurrent duplicate requests. A changed source hash or embedding model creates a distinct immutable document version.

## API

All routes require a verified bearer token and active tenant membership.

| Method | Route | Tenant permission |
|---|---|---|
| POST | /api/v1/rag/documents | documents:write |
| POST | /api/v1/rag/documents/upload | documents:write |
| POST | /api/v1/rag/search | rag:search |
| GET | /api/v1/rag/documents/{document_id} | documents:read |
| GET | /api/v1/rag/documents/{document_id}/chunks/{chunk_id} | documents:read |

The text document endpoint returns the stored source text and its recomputed hash status. The upload endpoint accepts files up to 10 MB and limits extracted text to 1 MB; PDF is capped at 500 pages, and DOCX archives are capped at 512 entries and 30 MB uncompressed. The parser does not execute embedded content, fetch external links, or write uploads to disk. It records the uploaded file SHA-256, sanitized display filename, parser, and media type. The chunk endpoint returns the source and chunk digests, offsets, excerpt, and three integrity booleans.

metadata_filter is a bounded JSON object and is applied as JSONB containment before ranking. It never replaces the tenant predicate.

## PostgreSQL and RLS

Apply migrations in lexical order:

- 0006_issuer_scoped_tenant_memberships.sql
- 0007_rag_pgvector.sql

The RAG migration installs the vector extension, creates the document and chunk tables, a cosine HNSW index, a GIN full-text index, and forced tenant RLS policies. The runtime role must be a non-superuser without BYPASSRLS. Grant it only the required table privileges:

~~~sql
GRANT SELECT, INSERT ON rag_documents, rag_document_chunks TO app_runtime;
~~~

Do not grant the application role ownership of these tables or BYPASSRLS. Do not connect browser clients directly to this database.

The schema is pinned to 1536-dimensional vectors. If the selected RUSA-AI or external embedding model returns a different dimension, do not override the environment variable alone: change the vector typmod, index, model, and integration fixtures together in a reviewed migration.

## Embedding provider configuration

Configure the actual OpenAI-compatible embedding endpoint through the deployment secret manager:

~~~bash
RAG_ENABLED=true
EMBEDDING_API_URL=https://embedding.internal.example/v1/embeddings
EMBEDDING_API_KEY=<secret-from-secret-manager>
EMBEDDING_MODEL=<deployed-embedding-model>
EMBEDDING_DIMENSIONS=1536
EMBEDDING_TIMEOUT_SECONDS=30
~~~

The endpoint must return the OpenAI-compatible data[].index and data[].embedding structure. The adapter validates item count, order, dimension, numeric values, and finite floats. It does not create synthetic embeddings or fall back to lexical-only results when the provider fails. RAG requests return a service/provider error instead.

Production embedding URLs must use HTTPS. Plain HTTP is permitted only for localhost development endpoints.

## MCP server

Enable MCP only after the API identity provider, PostgreSQL, RAG schema, embedding provider, and public resource URL are configured:

~~~bash
MCP_ENABLED=true
MCP_RESOURCE_SERVER_URL=https://api.example.com/mcp
MCP_ALLOWED_HOSTS=api.example.com,api.example.com:443,api.example.com:*
MCP_ALLOWED_ORIGINS=https://trusted-mcp-client.example
~~~

The MCP endpoint uses the official Python MCP SDK Streamable HTTP transport. It acts as a resource server: it verifies the same signed access token as the API, requires the rag:search scope, and does not issue tokens. The issuer and audience are checked by the existing JWT/JWKS verifier. The SDK's resource-URL comparison is disabled because this identity provider uses its own audience identifier; the configured AUTH_AUDIENCE is still verified.

Only these read-only tools are registered:

- rag_search(query, limit, metadata_filter)
- rag_get_document(document_id)

Each tool re-resolves active issuer-scoped tenant membership and checks database-backed role permissions. A client cannot register a tool or supply an arbitrary server-side function name. The MCP server is stateless and uses JSON responses with a 1 MiB request-body limit. Host allowlisting is mandatory; browser origins, if any, must be listed explicitly.

When MCP is disabled, /mcp returns 503. If MCP_ENABLED=true but any required setting is missing, startup fails closed.

## Retrieval evaluation

The versioned dataset is tests/evaluation/rag_retrieval.json. It contains 12 source documents and 12 retrieval queries. The evaluator uses the configured live embedding endpoint and the real PostgreSQL hybrid search path; test doubles are not used by the evaluation script.

Run it through the **RAG Live Retrieval Evaluation** GitHub Actions workflow after configuring the protected `staging` environment with `RAG_EVAL_DATABASE_URL`, `EMBEDDING_API_URL`, `EMBEDDING_API_KEY`, and the `EMBEDDING_MODEL` repository variable. The evaluator creates a unique tenant namespace per run, verifies that the database role is a non-superuser without `BYPASSRLS`, and rolls back all fixture writes when finished.

The evaluator reports:

| Metric | Target |
|---|---:|
| Recall@5 | >= 0.90 |
| MRR@10 | >= 0.80 |
| NDCG@10 | >= 0.85 |
| Citation integrity | 1.00 |

A non-zero exit code means one or more targets were missed. Fixture writes are rolled back; no pre-existing tenant data is modified.

## Evidence and release boundary

Automated tests cover deterministic chunk offsets, embedding response validation, issuer-scoped membership, MCP bearer authentication and configuration, PostgreSQL migration/RLS, real SQL hybrid ranking, idempotent ingestion, and citation integrity.

A passing CI run does not prove that the deployment's real embedding provider is reachable or semantically suitable. Before production approval, run the retrieval evaluator against the actual configured embedding model and staging PostgreSQL, test the public MCP URL from a real MCP client, and complete cross-tenant negative tests with the deployed non-superuser runtime role.

This increment does not change the repository's production release decision: **NO-GO until all stage and deployment gates pass.**
