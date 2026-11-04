# V6 Authentication Foundation

## Implemented

- JWT access-token verification through a deployment-configured HTTPS JWKS endpoint.
- Explicit signing-algorithm allowlist limited to RS256 and ES256.
- Signature verification plus issuer, audience, expiry and subject validation.
- Required UUID `tenant_id` claim.
- Protected `GET /api/v1/me` endpoint.
- Fail-closed behavior when authentication is not configured.
- HTTP 401 with Bearer challenge for missing or invalid credentials.
- Reusable scope dependency for subsequent protected routes.
- Unit tests for algorithm rejection, required claims, JWKS key resolution, missing credentials and unconfigured identity.

## Configuration contract

| Variable | Purpose |
|---|---|
| `AUTH_JWKS_URL` | Trusted HTTPS JWKS endpoint |
| `AUTH_ISSUER` | Exact expected issuer |
| `AUTH_AUDIENCE` | Expected API audience |
| `AUTH_ALGORITHMS` | Allowlist: RS256 and/or ES256 |

The JWKS endpoint is deployment-controlled configuration. Never accept a JWKS URL, issuer, audience or algorithm from request parameters or token claims.

## Explicitly not implemented

This is authentication, not complete authorization. There is no authoritative tenant-membership database, role freshness check, token revocation list, resource ownership lookup, database RLS integration or durable audit log yet. The tenant claim is cryptographically authenticated but still needs to be checked against authoritative membership before business resources are exposed.

## Release impact

This change advances the API identity foundation only. It does not change the platform production release decision: **NO-GO**.
