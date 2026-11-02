# V6 Tenant Authorization and Persistence Foundation

## Implemented in this increment

- SQLAlchemy 2.x persistence model for tenant memberships.
- PostgreSQL connection support through psycopg 3.
- Process-local SQLAlchemy engine pool with pre-ping and bounded recycle interval.
- Tenant membership lookup keyed by the verified JWT subject and tenant UUID.
- Membership status enforcement: only `active` membership is authorized.
- The role returned to the API is read from authoritative database state, not trusted from JWT role claims.
- `GET /api/v1/tenant/context` demonstrates a tenant-protected endpoint.
- PostgreSQL migration creates membership uniqueness constraints, status check, index, and forced row-level security.
- Tenant context is set transaction-locally using PostgreSQL `set_config(..., true)` before the membership lookup.
- SQLite-backed unit tests cover active, absent, cross-tenant and suspended memberships plus the API contract.

## Database setup

1. Provision PostgreSQL 15+ using a dedicated migration owner and a separate runtime application role.
2. Apply `apps/api/migrations/0001_tenant_memberships.sql` with the migration role.
3. Grant the runtime role only the minimum required SELECT privileges for this table. Do not grant it ownership, superuser, or `BYPASSRLS`.
4. Configure `DATABASE_URL=postgresql://...` in the API deployment secret store. The API normalizes this to the psycopg 3 SQLAlchemy dialect.
5. Provision membership records through a trusted administrative/onboarding process. No public membership-write endpoint is provided.

The migration forces row-level security. Its policy uses the transaction-local `app.tenant_id` setting. The application sets this setting from the cryptographically verified principal before querying membership. A missing tenant context yields no visible rows.

## Important limitations

- This increment does not provision a live PostgreSQL service or apply the migration to a production database.
- CI exercises repository logic against SQLite; PostgreSQL RLS behavior still requires integration tests against a real PostgreSQL instance and the actual restricted runtime role.
- There is not yet a trusted invitation/provisioning workflow, organization lifecycle, membership audit event, role-to-permission matrix, resource ownership checks, or revocation propagation.
- SQLite unit tests do not emulate PostgreSQL row-level security.
- The generic database session must not be used for tenant-owned business queries unless the caller establishes tenant context and the RLS policy is present.

## Release status

**NO-GO.** The API now has a database-backed tenant membership authorization slice, but the full platform remains incomplete. Do not expose notebook, agent, provider, or repository resources until PostgreSQL integration tests, tenant-scoped resource models, audit controls, and authorization tests pass.
