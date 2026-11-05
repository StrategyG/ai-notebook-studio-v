# ADR-0002: Tenant identity and role authority boundary

- **Status:** Proposed — requires Master Architect acceptance
- **Date:** 2026-11-05
- **Scope:** AI Notebook Studio API and Supabase tenant authorization
- **Related gate:** P0-04 — tenant schema and identity reconciliation

## Context

The Notebook API verifies an external identity token and must resolve an active membership using
`(tenant_id, issuer, subject)`. The API membership record carries the exact OIDC issuer, opaque
subject, an application role, and a lifecycle `status`. The API role policy is evaluated from the
database membership, not from role claims supplied by the token.

The Supabase migration defines `public.tenant_memberships` using `user_id UUID REFERENCES
auth.users(id)`, with a different role vocabulary. These are not interchangeable schemas:
an OpenID Connect `sub` is an opaque identifier scoped to an issuer and is not generally
convertible to a Supabase Auth UUID.

## Proposed boundary

1. The API identity key is the validated pair `(issuer, subject)`, and the membership lookup
   key is `(tenant_id, issuer, subject)`. The issuer is taken from the verified JWT `iss` claim
   and compared exactly with deployment configuration (`auth_issuer`). The issuer is persisted
   alongside subject in the API membership table.
2. The API authorizes tenant requests from the active API membership record. Token role
   claims are informational only and must never grant API permissions.
3. The API membership role vocabulary is exactly `owner`, `admin`, `editor`, `member`,
   and `viewer`. Unknown values are rejected at the database boundary and fail closed in
   application authorization.
4. Supabase `auth.users.id` and Supabase tenant membership remain the authority for
   Supabase Data API row-level security. Its role vocabulary (`owner`, `admin`, `member`,
   `billing_viewer`) is separate from API roles.
5. Any cross-system identity link must be explicitly provisioned and verified as a mapping
   from `(issuer, subject)` to `auth_user_id`. No UUID cast, email-based implicit match,
   or token-supplied role translation is permitted.
6. Role translation, when required, must be a versioned allow-listed mapping with explicit
   tests. Unknown roles map to no permissions.

## Implementation in this change

- Add a database check constraint to the API membership model.
- Add a PostgreSQL role-constraint migration using `NOT VALID`.
- Add an issuer migration that leaves legacy issuer values NULL until an operator verifies
  their identity-provider provenance; the runtime resolver never authorizes a NULL issuer.
- Replace subject-only membership uniqueness with `(tenant_id, issuer, subject)` uniqueness.
- Add a regression test proving that a Supabase-only `billing_viewer` value cannot be
  inserted into the API membership table.

This change does **not** modify the Supabase schema, live data, JWT configuration, or
production identity-provider settings.

## Acceptance gates before P0-04 can close

- Master Architect accepts or revises this identity boundary.
- Production issuer and audience are verified against the actual identity provider.
- The API membership role inventory is reviewed; legacy values are reconciled.
- Legacy membership issuers are backfilled only from verified identity-provider records; the
  migration is not considered complete while active legacy rows remain issuer=NULL.
- The PostgreSQL constraint is validated after the inventory is clean.
- Supabase RLS policies are tested using real authenticated users from separate tenants.
- A staging integration test proves that one authenticated subject maps to the intended
  Supabase user and tenant membership, without email guessing or cross-tenant access.
- Revocation behavior is verified across both API membership and Supabase RLS.

## Rollback

If the role constraint blocks a legitimate API role, stop the rollout and use an approved
forward migration to add the reviewed role and matching permission policy. To roll back
this schema constraint, drop `ck_tenant_memberships_role` in a reviewed database migration.
Do not weaken authorization by accepting arbitrary role strings.
