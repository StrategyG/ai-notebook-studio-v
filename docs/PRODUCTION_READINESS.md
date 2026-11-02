

## V6 feature-branch update — authentication foundation

The feature branch `feat/institutional-v6-auth-foundation` adds a JWT/JWKS verifier, fixed signing-algorithm allowlist (RS256/ES256), issuer/audience/expiry/subject validation, a required UUID tenant claim, a protected identity endpoint and a reusable scope guard. This supersedes the earlier statement that no JWT verifier exists **on that feature branch only**. It does not add authoritative tenant membership, resource authorization, revocation, database persistence, RLS, or a durable audit trail. The existing production decision remains **NO-GO**. Tests and CI for the exact feature-branch commit must be observed before treating the change as verified.

See [V6 authentication security note](SECURITY-AUTH-V6.md) and [V6 implementation status](IMPLEMENTATION-STATUS-V6.md).
