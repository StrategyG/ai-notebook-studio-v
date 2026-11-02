

## V6 implementation branch update

The feature branch `feat/institutional-v6-auth-foundation` adds a first verified-identity slice:

- JWT/JWKS signature verification using PyJWT.
- RS256/ES256 algorithm allowlist, issuer/audience/expiry/subject checks.
- Required UUID `tenant_id` claim and bounded role/scope claims.
- Protected `GET /api/v1/me` and reusable scope dependency.
- Fail-closed behavior when identity configuration is absent.

See [V6 authentication security note](docs/SECURITY-AUTH-V6.md). This is not complete tenant authorization: membership lookup, persistence, RLS, revocation and resource ownership checks remain unimplemented. The production release decision remains **NO-GO**. These changes are on the feature branch until its pull request is reviewed and merged.
