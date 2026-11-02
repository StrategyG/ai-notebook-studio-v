# Stage 1 — Platform Foundation Implementation Status

**Status:** PARTIAL — initial domain/API skeleton only. No production backend service is deployed.

## Implemented in `apps/api`

- FastAPI app shell with versioned metadata, liveness and fail-closed readiness endpoints.
- Versioned Pydantic task contract and explicit task transition state machine.
- Effective permissions formed by intersection of principal/agent/project grants; delegation cannot widen permission sets.
- Action-bound HIGH/CRITICAL approval evidence matching tenant, project, target, operation, risk and content digest.
- DAG dependency validation, cycle detection, missing-node rejection and longest-path delegation-depth enforcement independent of node traversal order.
- Internal agent descriptor with immutable identity/version, capabilities, supported task types/protocols, tenant/project scope, resource limits and health; eligibility fails closed unless available and in scope.
- Versioned event envelope with event ID, project, actor, source/target, correlation ID, idempotency key, timestamp, aggregate version and bounded top-level payload shape.
- Tests for lifecycle, approval, grant intersection/immutability, DAG ordering/cycle/depth, agent eligibility and event validation.
- Python CI workflow for compilation, Ruff and tests with coverage threshold; Dependabot now includes pip dependencies.

## Local verification

Environment: Python 3.13.5 (the CI workflow targets Python 3.12).

Command:

```bash
cd apps/api
PYTHONPATH=src pytest --cov=ai_notebook_api --cov-report=term-missing --cov-fail-under=85 -q
```

Result: **25 tests passed; 93.78% statement coverage**. Three additional consecutive plain pytest runs also passed after fixing the DAG depth calculation. This is local evidence, not a GitHub CI result. Python CI must pass on the current commit before its result is considered verified.

## Explicit NOT IMPLEMENTED / NOT VERIFIED

- Database connection pool, migrations and actual persistence.
- Supabase Auth/JWT signature verification, session lifecycle and key rotation.
- Tenant membership/object-level authorization at API endpoints.
- Approval storage, atomic one-time consumption, durable append-only audit store.
- Transactional outbox, event delivery/replay, SSE and persisted idempotency.
- Agent registration persistence, authenticated dispatch and A2A transport.
- MCP client/server registry and tool authorization execution.
- Provider gateway, BYOK vault, notebook data service, Colab/GitHub/Supabase adapters.
- Runtime/repository sandbox, queue worker, rate limiting and operational telemetry.
- Dependency lockfile/SBOM and reproducible dependency-resolution proof.

Readiness currently validates configuration shape only. It must not be treated as database or identity health. No protected business write route is exposed in this stage.

## Exit criteria still outstanding

1. Implement and test real JWT/JWKS validation and principal construction.
2. Implement database migrations, RLS policies, repository layer and rollback tests.
3. Add durable event outbox, audit event store and action-bound approval persistence/consumption.
4. Add tenant/project/object authorization integration tests, including negative cross-tenant cases.
5. Add operational auth/database health probes and secure deployment config.
6. Pass Python CI, Android CI asset gate and CodeQL on a single reviewed commit.
