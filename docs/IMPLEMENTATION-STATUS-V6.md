# AI Notebook Studio V6 — Implementation Status

**Working branch:** `feat/institutional-v6-auth-foundation`  
**Baseline:** `main` at `1e0b8350c002f9b86b4c4f6c72a0f7ab81a377ae`  
**Scope of this increment:** API authentication foundation  
**Production decision:** **NO-GO**

## Repository facts observed before changes

- Default branch is `main`.
- Android WebView shell and its security policy are present.
- API domain skeleton exists under `apps/api`.
- Existing Supabase migration and SQL RLS test assets exist, but no live Supabase project or deployment was verified.
- The root React-named HTML file is an 88-byte placeholder.
- The tree contains incomplete base64 gzip UI payload shards; the expected complete `index.html` and `docs.html` assets were not present as normal source files.
- The backend had no JWT/JWKS verifier or protected identity endpoint.
- No live AI provider, BYOK vault, notebook persistence/runtime, A2A transport, MCP registry or production deployment was verified.

## This increment

| Requirement | Implementation | Status |
|---|---|---|
| JWT signature verification | PyJWT + configured JWKS key resolution | IMPLEMENTED_NOT_VERIFIED |
| Algorithm restriction | RS256/ES256 allowlist | IMPLEMENTED_NOT_VERIFIED |
| Issuer and audience | Exact configured issuer and audience passed to verifier | IMPLEMENTED_NOT_VERIFIED |
| Expiry and required claims | exp, iss, aud, sub required | IMPLEMENTED_NOT_VERIFIED |
| Tenant claim shape | UUID tenant_id required | IMPLEMENTED_NOT_VERIFIED |
| Identity endpoint | Protected GET /api/v1/me | IMPLEMENTED_NOT_VERIFIED |
| Scope guard | Reusable fail-closed dependency | IMPLEMENTED_NOT_VERIFIED |
| Tenant membership lookup | No authoritative membership store | NOT_IMPLEMENTED |
| Resource-level authorization | No persistence/ownership model wired to API | NOT_IMPLEMENTED |
| Token revocation | Not implemented | NOT_IMPLEMENTED |
| Database connectivity and migrations | Not wired to API | NOT_IMPLEMENTED |
| RLS enforcement from API | Not verified | NOT_IMPLEMENTED |
| Durable audit and outbox | Not implemented | NOT_IMPLEMENTED |
| AI gateway, BYOK, notebook runtime | Not implemented | NOT_IMPLEMENTED |
| MCP/A2A, integrations, agent runtime | Not implemented | NOT_IMPLEMENTED |
| UI restoration | Payload shards incomplete; no verified restored source | BLOCKED |

## Security boundary

A valid JWT proves that the configured issuer signed the claims. It does not establish that the subject remains a tenant member, that a role is current, or that a resource belongs to that tenant. Business routes must remain unavailable until authoritative membership and resource authorization are implemented. The identity endpoint returns only a bounded, verified identity projection and never echoes the bearer token.

## Verification still required

- Install project dependencies in a clean Python 3.12 environment.
- Run `ruff check src tests`.
- Run `pytest --cov=ai_notebook_api --cov-report=term-missing --cov-fail-under=85`.
- Observe Python CI on the exact feature-branch commit.
- Perform integration tests against a controlled JWKS issuer with real signed tokens.
- Verify key rotation, unknown `kid`, expired token, wrong issuer, wrong audience, malformed tenant claim and unsupported algorithm.
- Independently review JWKS egress policy and token claim contract with the chosen identity provider.

## Release gate

This increment does not authorize production deployment. Keep the platform **NO-GO** until the full identity/tenant authorization model, persistence, isolation, audit, integrations, UI assets, runtime sandbox, operational controls and release evidence are implemented and verified.
