

## V6 feature-branch delta

The branch `feat/institutional-v6-auth-foundation` now contains a JWT/JWKS verification slice with an explicit RS256/ES256 allowlist, issuer/audience/expiry/subject checks, a required UUID tenant claim, a protected identity endpoint and reusable scope enforcement. This is a code-level authentication foundation, not full authorization. Tenant membership, resource ownership, revocation, persistence, RLS and audit storage remain absent. The score table above remains the historical baseline assessment; no new overall score is assigned until the branch test suite and CI evidence are available. Production remains **NO-GO**.

See [V6 authentication security note](SECURITY-AUTH-V6.md) and [V6 implementation status](IMPLEMENTATION-STATUS-V6.md).
