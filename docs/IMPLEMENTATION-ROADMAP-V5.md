# V5.0 implementation roadmap and stage gates

**Current position:** Stage 0 static discovery completed; Stage 1 backend/domain skeleton partially implemented.  
**Release decision:** NO-GO.

## Stage 0 — Discovery and baseline

**Deliverables:** inventory, static assessment, baseline status matrix, architecture proposal, integration compatibility matrix, acceptance test plan, decision record.

**Current result:** the source archive and repository were inspected. The repository is presently an Android WebView shell, and source assets are absent from the checked-in branch. No product backend or external integration was found.

**Exit criteria:** baseline is versioned; all current claims are tied to evidence; all unknowns are explicitly marked NOT VERIFIED.  
**Status:** COMPLETE for static discovery; live integration and device verification remain NOT RUN.

## Stage 1 — Platform foundation

Build only the shared foundation needed by all workspaces:

1. Recover/rebuild maintainable React/TypeScript UI source and create responsive routing/workspace shell.
2. Add FastAPI modular monolith with typed/versioned API contracts.
3. Add authentication and tenant/project/workspace membership.
4. Add object-level authorization and policy decision points.
5. Add Supabase/Postgres migrations, baseline RLS policies and SQL policy tests.
6. Add project/workspace/conversation/notebook metadata models without collapsing domain ownership.
7. Add task, approval, artifact and append-oriented audit registries.
8. Add transactional outbox, correlation IDs and SSE state updates.
9. Add provider/integration secret storage abstraction, encryption and rotation design.
10. Add feature flags, structured logs, OpenTelemetry traces and health endpoints.

**Initial implementation committed:** `apps/api` contains the FastAPI shell, task contract/FSM, permission intersection, action-bound approval evidence, DAG validation, agent descriptor, event envelope and liveness/readiness endpoints. Local evidence: 25 tests pass at 93.78% statement coverage on Python 3.13.5. A Python 3.12 CI workflow is committed but its first run is still pending verification. There is no database, JWT verifier, durable audit/outbox, auth/session route or external integration yet.

**Exit criteria:** tenant-isolation tests, auth lifecycle, audit/approval tests, migration reset tests, responsive workspace shell and reproducible CI all pass.

## Stage 2 — AI foundation

- Provider registry and model capability catalogue.
- Server-side provider adapters for OpenAI, Gemini, Anthropic, OpenRouter and compatible providers.
- BYOK or managed key custody through a backend vault.
- Streaming chat, conversation history and project-scoped retrieval.
- Usage/cost attribution, timeouts, retry budgets and model fallback.
- Structured output and tool-call validation.
- Prompt injection and secret-exfiltration tests.

**Exit criteria:** AT-01 passes; no provider secret appears in frontend, logs, notebook outputs or artifacts.

## Stage 3 — Notebook and Colab

- Canonical notebook document schema and version history.
- Cell operations and .ipynb import/export.
- Autosave and conflict/version handling.
- Runtime/session/execution registry separated from notebook documents.
- Official Colab MCP adapter with real auth, runtime discovery, session lifecycle, execution streaming, executionId recovery and cancellation.
- Output handling; rich outputs only after a documented/tested supported path is proven.
- Local isolated runtime adapter for deterministic development/testing.
- Clear separation between normal notebook execution and hostile repository-code sandbox.

**Exit criteria:** AT-02, AT-03 and AT-04 pass with actual runtime evidence; kernel loss does not corrupt notebook documents.

## Stage 4 — GitHub and Supabase workspaces

- GitHub App installation and least-privilege repository selection.
- Repository explorer, branch/commit/diff, PR and Actions read workflows.
- Feature-branch patch workflow and approval-bound PR creation.
- Supabase project adapter, schema/RLS/auth/storage/function inspection.
- Version-controlled migration proposals and local/staging validation.
- Approval-bound production apply workflow and recovery strategy.

**Exit criteria:** AT-05 and AT-06 pass on disposable test projects. No production writes have been performed without approval.

## Stage 5 — A2A and MCP foundation

- Official SDK compatibility spike and pinned versions.
- Agent registry, identity, capability catalogue and trust classification.
- A2A Agent Card discovery/auth/task/message/artifact adapters.
- MCP remote server registry, version profile, tool/resource discovery and schema validation.
- Central policy enforcement for all MCP tool calls.
- Agent/task scoped auth, timeouts, output caps, idempotency and audit.
- External content handling and SSRF safeguards.

**Exit criteria:** AT-08, AT-09 and AT-10 pass; unauthorized tool and task calls are denied.

## Stage 6 — Multi-agent engineering workflows

Begin with a bounded role set: Planner, Research/Architecture, Repository Analyst/Coder, Security Reviewer, Test Evaluator, Notebook/Data Specialist, Database Specialist and Release Reviewer.

- Dependency-aware task graph.
- Independent patch review.
- Bounded delegation depth, retries, cost and time.
- Artifact/provenance exchange.
- Failure recovery and human intervention.
- External A2A agents treated as untrusted and permission-scoped.

**Exit criteria:** AT-11 through AT-15 pass. Agent collaboration yields a repeatable improvement over a single-agent baseline.

## Stage 7 — Quality and operations

- Unit/integration/E2E/contract/security/performance/resilience tests.
- A2A compatibility tests and MCP tool schema/permission tests.
- AI evaluation datasets for groundedness, tool selection, permission adherence and task quality.
- Visual regression and viewport checks.
- Correlated observability, budget alerts, runtime/provider health and SLOs.
- Backup, restore, retention, export and deletion workflows.
- Operational runbooks and incident drills.

**Exit criteria:** AT-16 through AT-18 pass. Metrics and SLOs are based on measured staging/production data.

## Stage 8 — Production assurance

- Threat-model and security review.
- Load/soak tests, restore drills and incident exercises.
- SBOM, dependency scanning, secret scanning and release provenance.
- Signed Android AAB / web deployment artifacts.
- Staged rollout, monitoring, rollback and owner-approved change window.
- Final human release approval.

**Exit criteria:** every release gate is PASS or approved WARNING; no critical/high unresolved blocker; exact release commit and signed artifacts are independently verified.

## Work ordering and dependencies

```text
Stage 0
  |
  v
Stage 1: Identity + tenant model + persistence + audit + approvals
  |
  +-------> Stage 2: AI providers/chat
  |
  +-------> Stage 3: Notebook/Colab
  |
  +-------> Stage 4: GitHub/Supabase
  |
  +-------> Stage 5: A2A/MCP
                 |
                 v
            Stage 6: multi-agent workflows
                 |
                 v
            Stage 7: quality and operations
                 |
                 v
            Stage 8: production assurance
```

Some implementation can proceed in parallel after the platform foundation provides stable identity, project, artifact, task and approval contracts. Do not build the multi-agent orchestration layer before those trust boundaries exist.

## Score discipline

The 9.0–9.3/10 target is a desired outcome, not a design score. Every score increase must be backed by actual test evidence, integration evidence, operational telemetry or independent review. Build success alone cannot increase functional or production-readiness scores.


## Stage 1 progress snapshot (2026-11-02)

**Status: PARTIAL — domain/API skeleton only.** The initial code is committed at `ca6ae2402333edec51dff76bfb3808b372c60649`. See [Stage 1 foundation status](STAGE-1-FOUNDATION.md).

The domain library is deliberately separate from persistence and transports: the task/agent/event types are not yet database entities, A2A wire messages or MCP requests. The API readiness endpoint checks configuration shape only. Do not deploy it as a ready production service.
