# AI Notebook Studio API — Stage 1 foundation skeleton

This package is the first backend code foundation in the V5 transformation. It contains a FastAPI modular-monolith shell and framework-independent domain contracts/policies. It does **not** yet connect to a database, Supabase Auth, AI providers, Colab, GitHub, A2A or MCP. No business-write endpoints are exposed.

## Local development

```bash
python -m pip install -e '.[dev]'
PYTHONPATH=src pytest
uvicorn ai_notebook_api.main:app --app-dir src --reload
```

The liveness endpoint returns 200. Readiness returns 503 until a PostgreSQL URL and HTTPS identity issuer/JWKS configuration are present. This is a configuration check only: no live database connectivity test or JWT verification is implemented. Never treat a configured URL as a verified dependency.

## Stage 1 code included

- Versioned task contract and explicit task-state transition table with terminal-state protection.
- Permission intersection for principal/project/task/agent grants; delegation cannot widen the resulting grant.
- Action-bound high/critical approval evidence matching exact tenant, project, target, operation, risk and content digest.
- Dependency DAG validation, topological order, cycle/missing-node detection and bounded delegation depth.
- Internal agent descriptor with version, capabilities, task types, protocol declarations, trust scope, resource limits and fail-closed eligibility check. This is not an A2A AgentCard wire codec.
- Versioned event envelope with correlation/idempotency metadata and bounded payload shape. Durable delivery requires a transactional outbox, not yet implemented.
- Liveness/readiness endpoints that do not report the platform ready by default.

## Not production complete

No database adapter, migrations, RLS, JWT/JWKS signature verification, auth/session route, tenant persistence, approval persistence, audit event store, transactional outbox, rate limiting, provider, Colab, GitHub, Supabase, MCP or A2A transport is included. Readiness remains false unless configuration is provided, and remains only a configuration check until real connectivity and verification are implemented.
