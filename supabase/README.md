# Supabase database foundation — CI-gated draft

The migration `migrations/20261102000000_platform_core.sql` creates the initial multi-tenant relational foundation for tenants/memberships, projects/memberships, workspace metadata, tasks/dependencies, approvals, artifact metadata, agent registry and audit events.

## Security intent

- Direct client table access is read-only in this initial schema.
- RLS limits rows by tenant/project membership. Project membership rows are visible only to the member themselves or project owner/admin; audit-stream reads are project owner/admin only.
- No direct client insert/update/delete is provisioned. Writes are reserved for a server-side API that must enforce user authorization before using a server credential.
- `service_role` bypasses RLS and is privileged. It must never be shipped to browser/Android or exposed to agents. Backend code must not blindly forward user input under service-role authority.
- The `private` SQL helpers are `SECURITY DEFINER`, use a fixed empty search path and fully qualified relation references. Function ownership and execution grants remain review items.

## Local CI

The repository includes a minimal `config.toml`, a pgTAP test suite and `.github/workflows/supabase-ci.yml`. GitHub Actions starts an isolated local Supabase stack, runs schema lint, then runs pgTAP:

```bash
supabase start
supabase db lint --local --fail-on error
supabase test db --local
```

CI uses no Supabase project ID, production password, access token or linked remote project. The local stack is disposable development infrastructure only.

## Verification status

**NOT RUN in this workspace.** This environment has no PostgreSQL server, Docker or Supabase CLI. The new GitHub Actions workflow is the first real execution attempt. Until the workflow completes successfully, migration syntax, RLS semantics and the pgTAP assertions remain **NOT VERIFIED**. Even after CI passes, independent security review and application-level tests through authenticated Supabase clients are still required.

## Deliberate limitations

No notebook documents, conversations, provider credentials, storage buckets/policies, outbox, row-level task transition history, approval-consumption function, retention/backup policy or auth configuration for real users is included. The initial migration is not a production deployment instruction.
