# AI Notebook Studio V5 — Engineering transformation workspace

This branch is an incremental transformation of the Android prototype into the V5 institutional engineering platform. It must not be described as production-ready until its documented release gates pass.

## Current stage status

- **Stage 0 — static discovery and architecture baseline:** documented. No live third-party integration was claimed.
- **Stage 1 — backend foundation:** initial FastAPI modular API skeleton added under `apps/api`. It includes typed task and agent contracts, task lifecycle rules, effective permission intersection, action-bound approval checks, DAG/delegation limits, event envelope metadata and readiness endpoints. This is a domain foundation, not a connected application backend.
- **Stages 2–8:** not implemented. See `docs/IMPLEMENTATION-ROADMAP-V5.md`.

## Documentation

- `docs/STAGE-0-BASELINE-AUDIT.md` — evidence-based repository inventory and baseline.
- `docs/STAGE-1-FOUNDATION.md` — implemented skeleton, local test evidence and explicit gaps.
- `docs/PLATFORM-ARCHITECTURE-V5.md` — proposed component boundaries and data ownership.
- `docs/PROTOCOL-INTEGRATION-MATRIX.md` — A2A, MCP, Colab, GitHub and Supabase compatibility requirements.
- `docs/SECURITY-THREAT-MODEL-V5.md` — initial trust boundaries and threat controls.
- `docs/ACCEPTANCE-TEST-PLAN.md` — acceptance tests AT-01 through AT-18.
- `docs/IMPLEMENTATION-ROADMAP-V5.md` — stage gates.
- `docs/adr/0001-modular-monolith.md` — initial architecture decision.

## API local development

```bash
cd apps/api
python -m pip install -e ".[dev]"
PYTHONPATH=src pytest
uvicorn ai_notebook_api.main:app --app-dir src --reload
```

Readiness returns 503 until PostgreSQL and HTTPS identity configuration are present. Tenant-protected APIs resolve active membership and role from the database; token-supplied role claims do not grant tenant permissions. UGAI task forwarding is separately disabled until server-side OAuth token exchange is configured.

## Product status

The original Android branch still has missing HTML assets. The frontend remains demo/static; AI providers, BYOK, notebook persistence/execution, Colab, GitHub App, Supabase, A2A, MCP, real orchestration and governance backends are not yet implemented. Do not embed credentials in the client.

## Release status

**NO-GO.** Keep PR #1 as draft. Android CI on the latest documented commit passed CodeQL but still fails the final exact-HTML asset gate. Python API tests pass locally at 93.78% coverage; Python CI on GitHub is pending verification after the source is committed. Release requires complete UI assets, real authorized integrations, tenant isolation, sandbox/security testing, device and responsive testing, observability, backup/restore validation and signed release artifacts.

## V6 implementation branch update

The feature branch `feat/institutional-v6-auth-foundation` adds a first verified-identity slice:

- JWT/JWKS signature verification using PyJWT.
- RS256/ES256 algorithm allowlist, issuer/audience/expiry/subject checks.
- Required UUID `tenant_id` claim and bounded role/scope claims.
- Protected `GET /api/v1/me` and reusable scope dependency.
- Fail-closed behavior when identity configuration is absent.

See [V6 authentication security note](docs/SECURITY-AUTH-V6.md). This is not complete tenant authorization: membership lookup, persistence, RLS, revocation and resource ownership checks remain unimplemented. The production release decision remains **NO-GO**. These changes are on the feature branch until its pull request is reviewed and merged.


## UGAI task integration (v1)

The Notebook API can proxy the canonical UGAI task lifecycle through a server-side
OAuth 2.0 token-exchange flow. The browser never receives UGAI OAuth client
credentials or the exchanged UGAI token.

Routes:
- `POST /api/v1/tasks` — requires an active tenant membership with
  `agents:run`; accepts an `Idempotency-Key` UUID.
- `GET /api/v1/tasks/{task_id}` — requires an active membership with
  `notebooks:read`.
- `POST /api/v1/tasks/{task_id}/cancel` — requires `agents:run`.

All three routes validate the Notebook access token, then resolve the active
tenant membership and application role from the database. The server exchanges
the inbound user token for a short-lived token whose audience is UGAI. UGAI
independently validates the exchanged token and checks project access. The
task payload does not contain caller-supplied `tenant_id`, `actor_id`, or
authorization roles.

Configure the API process through a secret manager:
- `UGAI_ENABLED=true`
- `UGAI_BASE_URL=https://...` (HTTPS origin only)
- `UGAI_AUDIENCE=...` (the exact UGAI API audience)
- `UGAI_TOKEN_ENDPOINT=https://...` (RFC 8693 token exchange endpoint)
- `UGAI_CLIENT_ID=...`
- `UGAI_CLIENT_SECRET=...`

Production startup fails closed if UGAI forwarding is not enabled or this
configuration is incomplete. The identity provider must preserve or explicitly
map the verified user subject, tenant and role/project claims into a token
whose issuer, signing keys and audience are accepted by UGAI. Token exchange
failure and UGAI outages do not trigger an automatic task resubmission.
Clients reconcile uncertain submissions using the same idempotency key.

The API implementation and tests do not prove that a real identity provider
supports token exchange or that Notebook and UGAI share the same production
issuer/claim mapping. Live staging authentication, tenant isolation and
Notebook → UGAI task execution remain release gates.
