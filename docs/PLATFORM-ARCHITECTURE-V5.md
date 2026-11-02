# AI Notebook Studio V5 — Target Platform Architecture

**Architecture status:** Proposed baseline, pending implementation and architecture review  
**Principle:** Modular monolith first; split services only where security, scaling, latency or reliability proves the need.

## 1. Architecture objective

Deliver one responsive engineering workspace where conversations, notebooks, repositories, database operations, runtimes and agents share a versioned project context while retaining independent data ownership and authorization boundaries.

A successful tool call, UI status change, agent response or build does not itself prove the underlying operation succeeded. External effects must be verified from the owning system.

## 2. Proposed deployment shape

The initial production topology should remain deliberately small:

```text
Web / PWA / Android client
          |
     HTTPS API
          |
  FastAPI modular monolith
   |        |          |
 Identity  Domain     Governance
   |        |          |
   |     Orchestrator  Approval / Audit
   |        |
   |     Internal Agent Runtime
   |        |
   +---- Capability & Policy Resolver
             |
      Integration Adapters
      |        |        |
    A2A      MCP     Provider APIs
      |        |        |
 External  GitHub /  Colab / Supabase
 Agents    other MCP     |
             servers     |
                         |
       Notebook Runtime / Isolated Repo Worker
                         |
                   Artifact Store

Persistence: Supabase/Postgres + object storage
Events: transactional outbox + SSE initially
Observability: structured logs + OpenTelemetry traces/metrics
```

## 3. Application modules

| Module | Owns | Must not own |
|---|---|---|
| Identity & Access | Users, sessions, memberships, roles, scoped grants | Provider or GitHub secrets in the browser |
| Projects & Workspaces | Project metadata, workspace membership, integration references | External repository or database state |
| Conversation | Threads, messages, model selection, usage references | Notebook document state |
| Provider Gateway | Provider adapters, model capabilities, usage/cost records | Raw keys in logs or client code |
| Notebook | Notebook documents, ordered cells, versions, import/export metadata | External kernel memory |
| Runtime Adapter | Runtime assignments, sessions, executions, kernel outputs/status | Canonical notebook source |
| Repository | Repository links, branch selection, analysis records, proposed patches | GitHub's commit history |
| Database Workspace | Supabase project references, schema snapshots, query plans, migration proposals | Supabase's actual remote schema state |
| Agent Registry | Internal agent identities, versions, declared capabilities and task limits | Privilege escalation |
| Orchestrator | Plans, dependency graph, assignment and result aggregation | Permission grants belonging to users |
| A2A Gateway | External agent discovery, authenticated task/message exchange | MCP tool authorization bypass |
| MCP Gateway | Server registry, tool schemas, resource references, per-call policy | Unrestricted arbitrary remote execution |
| Task Registry | Task contracts, state transitions, attempts, dependencies | Unverified UI task status |
| Artifact Registry | Artifact metadata, provenance, object links, access control | Source-of-truth repository contents |
| Approval | Action-bound requests, reviewers, decisions, evidence hashes | Blanket approval for future unrelated actions |
| Audit & Observability | Append-oriented audit events, correlation, logs and traces | Mutable business state masquerading as audit |

## 4. Data ownership

| Data | Canonical owner | External reference |
|---|---|---|
| Project/workspace metadata | Application database | Project and workspace IDs |
| Conversation history | Conversation store | Conversation ID |
| Notebook structure and cell source | Notebook document store | Notebook ID + version |
| Kernel variables/imports | External runtime/session | Runtime and session resource name |
| Execution result | Execution registry + artifact store | Execution ID + runtime provenance |
| Git commit/tree/branch | GitHub | Repo ID, branch, commit SHA |
| Supabase schema and data | Supabase/Postgres | Project ref, schema version |
| Agent task lifecycle | Task Registry | Task ID + parent task ID |
| Agent capability/version | Agent Registry | Agent ID + version |
| A2A task state | Remote A2A agent, mirrored locally | Peer URL + remote task ID |
| MCP tool catalog | Remote MCP server, cached locally | Server identity + tool name/schema hash |
| Generated files/reports | Artifact Registry + object store | Artifact ID + content digest |
| Approval evidence | Approval service | Approval ID + exact proposal/diff digest |
| Audit events | Append-oriented audit store | Event ID + correlation ID |

**Notebook/runtime invariant:** notebook document state is canonical in the application. Runtime state is ephemeral and separately observed. Losing a kernel must not silently change or delete the notebook document.

**Repository invariant:** GitHub remains the canonical owner of committed source and history. A local agent workspace is a disposable working copy, not the canonical repository.

## 5. Orchestration model

Use a DAG of bounded tasks instead of unrestricted agent-to-agent loops.

Each task contract must include:

- task_id, parent_task_id, project_id, correlation_id
- requesting principal and assigned agent identity/version
- objective and normalized input references
- required capabilities and task-scoped permissions
- risk class and required approval policy
- dependencies and delegation depth
- acceptance criteria and expected artifacts
- timeout, retry budget and resource/cost budget
- idempotency key and current state

State transitions:

`CREATED → PLANNED → ASSIGNED → RUNNING → REVIEW → VALIDATION → APPROVAL → COMPLETED`

Additional terminal/intermediate states: `WAITING`, `BLOCKED`, `FAILED`, `CANCELLED`, `EXPIRED`.

Enforce:
- strict transition validation;
- maximum delegation depth;
- cycle detection;
- bounded retries;
- idempotency on external side effects;
- budget and timeout limits;
- permission checks at execution time;
- persisted state before publishing the next event.

The orchestrator must not mint or widen subordinate authority. Every delegated action is constrained by the intersection of user grant, workspace policy, task grant, agent capability, and tool policy.

## 6. Initial agent roster

Do not instantiate 15 separate always-running agents merely to match a list. Begin with capability-scoped roles:

1. Master Orchestrator / Planner
2. Research & Architecture
3. Repository Analyst / Coding
4. Security Reviewer
5. Test & Evaluation
6. Notebook / Data Science
7. Database Specialist
8. Release & Documentation

The coding agent must not be the sole reviewer of its own patch. Security-sensitive and release actions require independent review. Additional specialist roles should be added only after measurable task-quality or latency improvements are demonstrated.

## 7. A2A and MCP separation

- A2A is used for discovering independent agents and exchanging tasks, messages, progress and artifacts.
- MCP is used by trusted clients/agents to discover and call authorized tools/resources.
- A2A results are untrusted external input. They never confer tool permissions.
- An external A2A agent receives only explicit task context and scoped authorization.
- Every MCP invocation is checked by the platform policy layer immediately before execution.
- Agent Cards and MCP tool schemas are validated and versioned. Capability descriptions are not proof of safety or quality.

## 8. Event envelope

Use a common event envelope for task, runtime, integration and approval updates:

```json
{
  "event_id": "uuid",
  "event_type": "task.status.changed",
  "project_id": "uuid",
  "actor_id": "principal-or-agent-id",
  "source": "orchestrator",
  "target": "workspace-stream",
  "correlation_id": "uuid",
  "idempotency_key": "stable-key",
  "occurred_at": "RFC3339 timestamp",
  "aggregate_id": "task-id",
  "aggregate_version": 12,
  "payload": {}
}
```

Initial delivery should use a transactional outbox and SSE to browser clients. Add WebSocket only where a measured bidirectional interaction requires it. Consumers must tolerate duplicate delivery and reconcile from persisted aggregate state.

## 9. Security boundaries

- Browser clients are untrusted; no provider key or Supabase secret key is shipped to them.
- API checks identity, tenant/project membership and object-level access on every request.
- External A2A/MCP peers are untrusted by default.
- Agent prompt/context does not override policy or permissions.
- Repository code executes only in an approved ephemeral isolation environment.
- Colab is a user-authorized compute integration, not the security sandbox for hostile repository code.
- No network egress from repository sandbox by default. Dependency acquisition uses an explicit, reviewed allowlist or prebuilt image.
- Production GitHub/Supabase writes require review and action-bound approval.
- Approval binds to exact target, diff/migration digest, risk, actor and expiry.
- Audit records are append-oriented and are not silently overwritten.

## 10. Proposed monorepo layout

This is a target layout, not a claim that these directories already exist:

```text
apps/
  web/                 # React + TypeScript responsive application
  api/                 # FastAPI modular monolith and A2A endpoint
  worker/              # isolated job orchestration / sandbox adapter
  android/              # existing Kotlin shell, retained as mobile client
packages/
  contracts/           # versioned API/event/task schemas
  ui/                  # shared design system
  agent-sdk/           # internal agent contracts and policy helpers
  integration-tests/   # A2A/MCP/provider contract tests
supabase/
  migrations/
  tests/
infra/
  sandbox/
  observability/
docs/
  adr/
  security/
tests/
  e2e/
  visual/
```

Before adopting this layout, restore the original UI artifact and decide whether the React UI can be recovered as a maintainable source project or must be rebuilt. Do not treat a compiled HTML artifact as the source of truth.

## 11. Technology decisions to validate with a vertical slice

| Concern | Proposed baseline | Validation required |
|---|---|---|
| Web UI | React + TypeScript + Vite | Recover/rebuild UI source; Playwright viewport tests |
| API | Python 3.12+ / FastAPI modular monolith | Dependency and deployment prototype |
| A2A | Official a2a-python SDK 1.0 | 1.0 interoperability with JS/TS peer |
| MCP | Official Python MCP SDK | 2026-07-28 stateless remote client and legacy peer compatibility |
| Persistence | Supabase Postgres + migrations + RLS | Tenant-isolation integration tests |
| Event delivery | Transactional outbox + SSE | Replay/duplicate/reconnect tests |
| Background jobs | Postgres-backed queue initially | Load test before choosing external broker |
| Notebook runtime | Colab MCP adapter + isolated local worker adapter | Real execution and output capability matrix |
| Repository execution | Ephemeral OCI sandbox | Threat model and escape/network tests |
| Artifact data | Object store with content hashes | Signed URL and access-control tests |
| Telemetry | OpenTelemetry | Trace correlation from API through worker and adapter |

## 12. Architecture decision records

Record every material choice in `docs/adr/`. Initial decisions are:
- ADR-0001: modular monolith before microservices.
- ADR-0002: notebook document and runtime state have different owners.
- ADR-0003: A2A and MCP are separate trust and communication layers.
- ADR-0004: external repository code does not execute in the Colab integration.
- ADR-0005: every high-impact side effect is gated by action-bound human approval.
