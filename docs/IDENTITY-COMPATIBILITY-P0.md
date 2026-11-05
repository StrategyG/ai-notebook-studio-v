# P0 Identity Compatibility — AI Notebook Studio V

**Canonical reference:** P0 contract draft in Universal-Generative-AI, docs/IDENTITY-COMPATIBILITY-P0.md.  
**Status:** Proposed mapping; implementation and live local-issuer interoperability NOT VERIFIED.

## Notebook identity adapter requirements

1. sub is the stable issuer-scoped user/workload subject and maps to Principal.subject.
2. tenant_id is a canonical UUID string and maps to the existing UUID Principal.tenant_id. Reject malformed values.
3. iss, aud, exp, iat, signature and configured algorithm allowlist remain mandatory. P0 common algorithm is RS256.
4. roles is a bounded array of coarse platform role strings. It is not a tenant permission grant.
5. scope is a bounded space-delimited capability string. Scope checks remain separate from tenant membership checks.
6. Every tenant-protected route resolves active membership by (tenant_id, subject, status=active). Persisted membership role and TENANT_ROLE_PERMISSIONS remain authoritative even if token roles claims platform_admin.
7. Notebook-to-UGAI calls use server-side audience-restricted token exchange. Preserve verified subject and tenant; derive project membership from trusted server-side membership/project records. Never accept caller-provided tenant_id, actor_id, role or project grants in task bodies.
8. Browser clients must never receive service client secrets or exchanged UGAI tokens.

## P0 tests to add

- UUID tenant claim accepted; malformed/non-UUID tenant rejected.
- Wrong issuer/audience/algorithm/signature/expiry rejected.
- Elevated token role with no active membership remains forbidden.
- Inactive membership remains forbidden.
- Token exchange preserves subject and tenant and issues only the UGAI audience.
- Project membership is resolved from trusted server state; cross-tenant/project requests are denied.
- Idempotent task submission and uncertain exchange failures do not silently resubmit work.

## Current evidence and limitations

The current Notebook auth parser already requires UUID tenant_id, validates issuer/audience/expiry/subject and reads bounded roles/scope. Tenant authorization is database-backed. README describes server-side UGAI token exchange, but live issuer compatibility and cross-service end-to-end tests are not proven by source inspection.

Do not weaken membership lookup or permit token roles to bypass persisted permissions. Do not mark this contract VERIFIED until CI and local issuer integration tests pass.
