# AI Notebook Studio API — V6 security foundation

This package is an incremental modular-monolith API foundation. V6 adds cryptographic JWT/JWKS access-token verification and a protected identity endpoint. It is **not** a complete production backend.

## Local development

```bash
python -m pip install -e '.[dev]'
PYTHONPATH=src pytest
uvicorn ai_notebook_api.main:app --app-dir src --reload
```

## Identity configuration

Configure these deployment-controlled variables:

- `AUTH_JWKS_URL`: HTTPS JWKS endpoint.
- `AUTH_ISSUER`: exact HTTPS token issuer.
- `AUTH_AUDIENCE`: expected API audience.
- `AUTH_ALGORITHMS`: comma-separated allowlist; supported values are RS256 and ES256.

The verifier checks the token signature using a key resolved from the configured JWKS endpoint and validates issuer, audience, expiry and subject. A verified token must also carry a UUID `tenant_id` claim. Only the verified subject, tenant identifier, roles and scopes are exposed by `GET /api/v1/me`; the bearer token is never returned.

Protected endpoints return 503 when identity configuration is absent and 401 for missing or invalid bearer credentials. `require_scopes` provides a reusable fail-closed scope dependency.

## Important security boundary

JWT verification proves that the configured issuer signed the claims. It does **not** prove that a user is an active member of a tenant, that a role is still current, or that a resource belongs to that tenant. Those checks require authoritative membership/resource persistence and revocation policy, which are not yet implemented. Therefore this commit does not expose notebook, project, agent, MCP, GitHub or other business-write routes.

## Current limitations

- No database connectivity or migrations are wired into the API.
- No tenant membership lookup, session revocation, authorization database or RLS enforcement.
- No durable approval store, audit ledger or transactional outbox.
- No AI provider gateway, BYOK vault, notebook runtime, MCP/A2A transport or integrations.
- Readiness still checks configuration presence, not live dependency health.
- The Android UI payload is not restored by this API change.

Do not deploy this API as production-ready solely because JWT verification is implemented.
