# V6 Tenant Authorization and Persistence Foundation

## Implemented in this increment

- SQLAlchemy 2.x persistence model for tenant memberships.
- PostgreSQL connection support through psycopg 3.
- Process-local SQLAlchemy engine pool with pre-ping and bounded recycle interval.
- Tenant membership lookup keyed by the verified JWT subject and tenant UUID.
- Membership status enforcement: only `active` membership is authorized.
- The role returned to the API is read from authoritative database state, not trusted from JWT role claims.
- Explicit tenant role-to-permission matrix and reusable permission dependency.
- `GET /api/v1/tenant/context` demonstrates a tenant-protected endpoint.
- PostgreSQL migration creates membership uniqueness constraints, status check, index, and forced row-level security.
- Tenant context is set transaction-locally using PostgreSQL `set_config(..., true)` before the membership lookup.
- SQLite-backed unit tests cover active, absent, cross-tenant and suspended memberships plus permission enforcement.
- GitHub Actions provisions PostgreSQL 16 and a non-owner, non-superuser, non-BYPASSRLS application role to test actual tenant row filtering.

## Database setup

1. Provision PostgreSQL 15+ using a dedicated migration owner and a separate runtime application role.
2. Apply `apps/api/migrations/0001_tenant_memberships.sql` with the migration role.
3. Grant the runtime role only the minimum required SELECT privileges for this table. Do not grant it ownership, superuser, or `BYPASSRLS`.
4. Configure `DATABASE_URL=postgresql://...` in the API deployment secret store. The API normalizes this to the psycopg 3 SQLAlchemy dialect.
5. Provision membership records through a trusted administrative/onboarding process. No public membership-write endpoint is provided.

The migration forces row-level security. Its policy uses the transaction-local `app.tenant_id` setting. The application sets this setting from the cryptographically verified principal before querying membership. A missing tenant context yields no visible rows.

## Important limitations

- This increment does not provision a live production PostgreSQL service or apply the migration to a production database.
- CI validates RLS against PostgreSQL 16 using a restricted runtime role, while unit tests use SQLite for portable repository logic.
- There is not yet a trusted invitation/provisioning workflow, organization lifecycle, membership audit event, resource ownership checks, or revocation propagation.
- The RLS policy currently protects the tenant membership table only. Every future tenant-owned table must receive an equivalent policy and isolation tests.
- The API does not yet include a durable role-change audit trail or role freshness cache invalidation because roles are resolved from the database per request.

## Release status

**NO-GO.** The API now has a database-backed tenant membership authorization slice, but the full platform remains incomplete. Do not expose notebook, agent, provider, or repository resources until all tenant-owned tables have RLS, PostgreSQL integration tests, audit controls, and authorization tests.
