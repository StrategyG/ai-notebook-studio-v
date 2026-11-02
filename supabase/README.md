# Supabase database foundation — draft / NOT RUN

The migration under `migrations/` creates a first multi-tenant relational foundation for tenants/memberships, projects/memberships, workspace metadata, tasks/dependencies, approvals, artifact metadata, agent registry and audit events.

## Security intent

- Client-facing table grants are `SELECT` only in this initial migration.
- RLS limits reads by tenant/project membership; audit stream reads require project owner/admin.
- No direct client insert/update/delete is provisioned. Writes are reserved for a server-side API that must implement user authorization before using the server credential.
- `service_role` bypasses RLS and is privileged. It must never be shipped to browser/Android or exposed to agents. The API must not blindly forward user input under service-role authority.
- The `private` SQL helpers are `SECURITY DEFINER`, have a fixed empty search path and use fully qualified table references. Review function ownership and execution grants during deployment.

## Test plan

A pgTAP RLS file is provided at `tests/database/rls.test.sql`. Run it only against a disposable local Supabase database after installing the Supabase CLI and starting the local stack:

```bash
supabase start
supabase db reset
supabase test db
```

**Current status: NOT RUN.** This environment has no PostgreSQL server, `psql`, Docker or Supabase CLI. The migration and tests have not been syntactically validated by PostgreSQL, and RLS must not be considered proven until the test suite passes and an independent review checks the policies and privilege grants.

## Deliberate limitations

This migration does not yet include notebook documents, conversations, provider credentials, storage buckets/policies, transactional outbox, row-level task transition history, approval-consumption function, retention/backup configuration or auth configuration. Those require domain-specific design and integration tests. The initial migration is not a production deployment instruction.
