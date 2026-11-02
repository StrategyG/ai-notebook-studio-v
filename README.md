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

Readiness returns 503 until PostgreSQL and HTTPS identity configuration are present. Even then it is only a configuration-presence check until database connectivity and JWT verification are implemented. No business write routes are currently exposed.

## Product status

The original Android branch still has missing HTML assets. The frontend remains demo/static; AI providers, BYOK, notebook persistence/execution, Colab, GitHub App, Supabase, A2A, MCP, real orchestration and governance backends are not yet implemented. Do not embed credentials in the client.

## Release status

**NO-GO.** Keep PR #1 as draft. Android CI on the latest documented commit passed CodeQL but still fails the final exact-HTML asset gate. Python API tests pass locally at 93.78% coverage; Python CI on GitHub is pending verification after the source is committed. Release requires complete UI assets, real authorized integrations, tenant isolation, sandbox/security testing, device and responsive testing, observability, backup/restore validation and signed release artifacts.
