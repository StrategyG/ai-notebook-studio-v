# UGAI and IM19 integration contract

**Status:** integration specification for the AI Notebook Studio backend. This is not proof of a live connection.

## 1. Architectural decision

AI Notebook Studio remains a notebook workbench and execution plane. It must not duplicate UGAI's global intelligence/orchestration functions or IM19's shared MCP gateway.

| Function | Owner | Studio responsibility |
|---|---|---|
| Agent planning, coordination and task orchestration | UGAI | Submit user intent; display task state and results |
| Global model/provider routing | UGAI | Display model/task metadata returned by UGAI |
| Decision workflows and policy evaluation | UGAI | Present decision context and approval UI where required |
| Remote MCP tool discovery and orchestration policy | UGAI | Do not maintain a competing global tool registry |
| Provider OAuth, encrypted provider credentials, provider quotas and MCP transport | IM19 | Never store or expose provider credentials |
| Notebook, project, cell and collaboration data | AI Notebook Studio | Own and persist notebook domain data |
| Notebook kernel, execution queue, worker isolation and artifacts | AI Notebook Studio | Own and enforce the complete execution boundary |
| User/tenant membership and notebook resource authorization | AI Notebook Studio identity/API | Enforce before task submission and execution |

Supported request path:

    Studio UI -> Studio API -> UGAI orchestration API -> IM19 MCP -> external providers
                                      |
                                      +-> Studio Execution API -> isolated notebook worker

Studio talks to IM19 only indirectly through a UGAI-governed workflow. Studio's notebook runtime is separate from both UGAI's reasoning runtime and IM19's MCP request runtime.

## 2. Authentication and identity rules

- The existing JWT/JWKS foundation validates signature, issuer, audience, expiry, subject and the UUID tenant claim. It does not yet prove current tenant membership, role freshness or notebook ownership.
- Do not expose task submission or execution routes until authoritative membership, object-level authorization, revocation policy and tenant isolation are implemented and tested.
- The Studio API authenticates the end user, then uses a separate short-lived service-to-service credential to call UGAI. The service token must have an exact UGAI audience and least-privilege scope.
- UGAI must receive actor_id and tenant_id from verified identity context, not prompt text, model output, notebook cell content or untrusted JSON fields.
- UGAI uses its own separately scoped, exact-resource token when it calls IM19. No IM19 bearer or provider token is forwarded to Studio.
- Studio's internal execution endpoint accepts only a short-lived service credential for the exact Studio execution audience. It checks task, tenant, actor, notebook, runtime profile and idempotency bindings.

## 3. Interface status (outbound clients implemented; server endpoints not implemented)

The following are target interfaces only. Do not document them as available until routes, authorization dependencies, schemas, persistence, queue and tests exist.

### Studio API to UGAI

- POST /api/v1/tasks: submit a notebook-associated task or analysis request.
- GET /api/v1/tasks/{task_id}: retrieve task status and bounded result references.
- POST /api/v1/tasks/{task_id}/cancel: request cancellation.

### UGAI to Studio execution service

- POST /api/v1/internal/executions: queue a specific notebook execution.
- GET /api/v1/internal/executions/{execution_id}: retrieve execution state.
- POST /api/v1/internal/executions/{execution_id}/cancel: request cancellation.

The execution request must reference an immutable notebook/cell revision or source digest, approved runtime profile and bounded parameters. It must not contain an arbitrary host filesystem path or provider credential.

### Required identifiers and state

Carry request_id, task_id, execution_id, idempotency_key, tenant and actor context, notebook/revision identifiers and distributed trace context. IDs used for authorization must be resolved from verified server-side records, not trusted because a client supplied them.

The UGAI workflow state machine is the source of truth for task state. The Studio client must parse these exact, case-sensitive values; it must not invent a parallel backend state vocabulary:

- `received`
- `observing`
- `planning`
- `executing`
- `verifying`
- `awaiting_approval`
- `awaiting_clarification`
- `blocked`
- `failed`
- `succeeded`
- `cancelled`

The Notebook client may map canonical workflow states to display-only labels (for example, `received` → `ACCEPTED`, `executing` → `RUNNING`, and `succeeded` → `COMPLETED`). Display labels must never be sent back as persisted workflow states. Task responses must echo the exact request ID supplied by the caller; status and cancellation responses must also echo the requested task ID. Unknown states or mismatched correlation IDs fail closed.

Studio execution states remain a separate, Studio-owned lifecycle:
`ACCEPTED -> QUEUED -> RUNNING -> SUCCEEDED | FAILED | CANCELLED`.

Cancellation is asynchronous. A timeout or lost response does not prove execution failed; reconcile by task or execution ID before retrying.

## 4. Notebook execution isolation

The notebook execution service remains a Studio-owned subsystem and must enforce:
- Ephemeral, non-root worker/container per execution or tenant-isolated runtime lease.
- Read-only base filesystem, isolated scratch volume, artifact allowlist and disk/output quotas.
- CPU, memory, process, concurrency and wall-clock limits.
- Default-deny egress; explicitly reviewed destinations only, with DNS rebinding and metadata-service protections.
- No ambient cloud credentials, host Docker socket, privileged mode, host mounts or inherited GitHub/Google/IM19 secrets.
- Dependency policy, package pinning, image digest verification and provenance capture.
- Bounded stdout/stderr, artifact size, retention and download authorization.
- Cancellation, lease expiry, crash recovery and idempotent queue semantics.

Do not run user code inside the UGAI process, IM19 gateway or API worker process.

## 5. Audit and data handling

- Notebook content, external provider results and model output remain untrusted.
- Persist only necessary task metadata and access-controlled artifact references in the orchestration layer.
- Never put credentials, bearer tokens, refresh tokens, OAuth codes, cookies or secret-bearing environment variables into notebook cells, prompts, outputs or logs.
- Correlate Studio, UGAI and IM19 events with request ID and trace ID while preserving each service's independent audit responsibility.
- Provider-side audit remains owned by IM19; UGAI records workflow provenance; Studio records notebook execution lifecycle.
- If audit fails before a privileged action, block that action. If audit fails after an action may have completed, mark the outcome uncertain and reconcile instead of retrying blindly.

## 6. Capability status from the inspected V6 branch

| Capability | Current evidence |
|---|---|
| Android WebView shell and API package skeleton | Present |
| JWT/JWKS verification foundation and protected identity endpoint | Present in V6 feature branch; real issuer integration unverified |
| Tenant membership, resource ownership authorization and revocation | Not implemented in inspected V6 status |
| React UI restoration | Blocked; repository status notes the React-named HTML file is an 88-byte placeholder |
| Studio outbound UGAI task client | Implemented in this branch with HTTPS-only transport, identity-bound token provider, request ID, idempotency key and bounded Pydantic payloads |
| UGAI task API and durable task store | Not implemented or verified |
| UGAI outbound Studio execution client | Implemented in UGAI integration branch; uses digest-only source reference, approved runtime profiles and bounded resource limits |
| Notebook execution API, queue and isolated worker | Not implemented or verified |
| MCP gateway inside Studio | Not required; must not be duplicated |
| Direct Studio-to-IM19 MCP connection | Prohibited by this architecture; use UGAI |
| Live end-to-end integration | Not tested |

## 7. Implementation sequence

1. Complete tenant membership, role freshness, revocation and resource-level authorization in Studio.
2. Restore maintainable Studio UI source and implement notebook/project persistence.
3. Implement the isolated notebook execution service and its queue, status, cancellation and artifact APIs.
4. Implement the authenticated UGAI task API and durable task store; wire the Studio client only after the endpoint and OpenAPI contract are published.
5. Implement Studio's authenticated execution API, queue and isolated worker; wire the UGAI execution client only after authorization and runtime controls pass.
6. Connect UGAI to IM19 using the existing audited MCP adapter, a managed OAuth token provider and a durable audit sink.
7. Add contract tests with fake services, then isolated staging tests with real OAuth audiences and separate tenant identities.
8. Enable features gradually behind server-side flags. Keep external writes disabled until approval verification and recovery tests pass.

**Production status: NO-GO.** This change records the responsibility split and required contracts only. It does not add routes, runtime execution, OAuth credentials, deployment configuration or a functioning live integration.
