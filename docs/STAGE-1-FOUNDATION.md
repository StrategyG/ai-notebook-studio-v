# Stage 1 — Platform Foundation Implementation Status

**Status:** PARTIAL — initial API/domain skeleton and draft DB schema only. No production backend service is deployed.

## Implemented in `apps/api`

- FastAPI app shell with versioned metadata, liveness and fail-closed readiness endpoints.
- Versioned Pydantic task contract and explicit task transition state machine.
- Effective permissions formed by intersection of principal/agent/project grants; delegation cannot widen permission sets.
- Action-bound HIGH/CRITICAL approval evidence matching tenant, project, target, operation, risk and content digest.
- DAG dependency validation, cycle detection, missing-node rejection and longest-path delegation-depth enforcement independent of node traversal order.
- Internal agent descriptor with immutable identity/version, capabilities, supported task types/protocols, tenant/project scope, resource limits and health; eligibility fails closed unless available and in scope.
- Versioned event envelope with event ID, project, actor, source/target, correlation ID, idempotency key, timestamp, aggregate version and bounded top-level payload shape.
- Python CI workflow for compilation, Ruff and tests with coverage threshold; Dependabot includes pip dependencies.

## Initial Supabase schema draft

Migration `supabase/migrations/20261102000000_platform_core.sql` defines tenants, memberships, projects, workspaces, tasks/dependencies, approvals, artifact metadata, agent registry and audit events. Direct client roles are read-only; RLS predicates use tenant/project membership helpers, while audit reads are restricted to project owners/admins. No authenticated client write path is enabled.

A pgTAP suite is drafted at `supabase/tests/database/rls.test.sql` for tenant isolation, scoped reads, audit visibility and direct-write denial.

**Database test status: NOT RUN.** There is no PostgreSQL server, Docker or Supabase CLI in the current environment. SQL syntax, grants, RLS function ownership and test behavior still require execution against a disposable Supabase instance and independent review.

## Local API verification

Environment: Python 3.13.5; CI targets Python 3.12.

Command:

```bash
cd apps/api
PYTHONPATH=src pytest --cov=ai_notebook_api --cov-report=term-missing --cov-fail-under=85 -q
```

Result: **25 tests passed; 93.78% statement coverage**. GitHub Python API CI [41410778494](https://github.com/StrategyG/ai-notebook-studio-v/actions/runs/41410778494) passed dependency installation, compile, Ruff and test/coverage steps on commit `c3910d0a9d9d60e41232a0a18cdb1c18d483f3bf`.

## Explicit NOT IMPLEMENTED / NOT VERIFIED

- Actual DB connection, migration execution, RLS test execution and restore.
- Supabase Auth/JWT signature verification, session lifecycle and key rotation.
- Tenant membership/object-level authorization in FastAPI routes.
- Approval storage, atomic one-time consumption, append-only audit writes and transactional outbox.
- Persisted agent registry, authenticated dispatch and A2A transport.
- MCP client/server registry and authorized tool execution.
- Provider gateway, BYOK vault, notebook document service, Colab/GitHub/Supabase adapters.
- Runtime/repository sandbox, queue worker, rate limiting and operational telemetry.
- Dependency lockfile/SBOM and reproducible dependency-resolution proof.

Readiness currently validates configuration shape only. It must not be treated as database or identity health. No protected business write route is exposed in this stage.

## Exit criteria still outstanding

1. Run and review the Supabase migration and pgTAP suite against a disposable local environment.
2. Implement and test real JWT/JWKS verification and principal construction.
3. Implement the DB repository, tenant/project/object authorization and RLS negative tests.
4. Add transactional outbox, durable audit events, approval persistence/atomic consumption and artifact access controls.
5. Add operational dependency probes and secure deployment config.
6. Pass Python CI, Android CI asset gate and CodeQL on a single reviewed commit.
