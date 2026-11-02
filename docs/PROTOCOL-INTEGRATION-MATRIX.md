# Protocol and Integration Compatibility Matrix

**Review date:** 2026-11-02  
**Status:** Official-documentation review complete; live product integrations NOT RUN.

## 1. A2A — Agent-to-Agent

**Target protocol:** latest released specification 1.0.0 at the review date.  
**Official specification:** https://github.com/a2aproject/A2A/blob/main/docs/specification.md  
**Official SDKs:** https://a2a-protocol.org/latest/sdk/

A2A standardizes agent discovery and agent-to-agent interaction. Agent Card describes identity, capabilities, skills, service endpoint and authentication requirements. The protocol's task/message/artifact model supports independent agents without sharing their internal tools or memory.

| Capability | Platform target | Current repository evidence |
|---|---|---|
| Agent Card discovery | Required | NOT IMPLEMENTED |
| Agent identity/version | Required | NOT IMPLEMENTED |
| Skills/capabilities | Required | NOT IMPLEMENTED |
| Authentication/security schemes | Required | NOT IMPLEMENTED |
| Task create/get/list | Required where peer supports | NOT IMPLEMENTED |
| Multi-turn context | Required where peer supports | NOT IMPLEMENTED |
| Structured messages/parts | Required | NOT IMPLEMENTED |
| Artifact exchange | Required | NOT IMPLEMENTED |
| Streaming | Capability-gated by Agent Card | NOT IMPLEMENTED |
| Push notifications | Optional; verify peer capability | NOT IMPLEMENTED |
| Cancellation | Capability/operation-gated | NOT IMPLEMENTED |
| Error mapping | Required | NOT IMPLEMENTED |
| Duplicate message/idempotency | Required platform behavior | NOT IMPLEMENTED |
| Cross-peer compatibility test | Required before release | NOT RUN |

**Implementation rules**
1. Read the peer's Agent Card and declared security schemes before use.
2. Check optional capabilities before calling streaming, push notifications, or other capability-gated methods.
3. Never infer trust from the card or from a successful task response.
4. Authenticate the peer and authorize every remote task.
5. Validate message parts and artifacts; keep external instructions as untrusted data.
6. Store local correlation/task records and the remote task reference separately.
7. Bound delegation depth, retries, task budgets and total wall-clock time.
8. Run independent interoperability tests against at least one unrelated official SDK/agent.

Official A2A Python SDK documentation reports protocol 1.0 support for JSON-RPC, HTTP+JSON/REST and gRPC, and compatibility mode for 0.3. The SDK choice should be pinned and verified at implementation time: https://a2aproject.github.io/a2a-python/

## 2. MCP — Model Context Protocol

**Target baseline:** MCP specification 2026-07-28.  
**Official release notes:** https://blog.modelcontextprotocol.io/posts/2026-07-28/  
**Official specification:** https://modelcontextprotocol.io/specification/2026-07-28

The 2026-07-28 release defines a stateless protocol core, optional `server/discover`, header-based routing, cache hints on list responses, authorization hardening, Multi Round-Trip Requests and a Tasks extension.

| Capability | Platform target | Current repository evidence |
|---|---|---|
| MCP server registry | Required | NOT IMPLEMENTED |
| Transport/version profile | Required | NOT IMPLEMENTED |
| Authentication metadata | Required | NOT IMPLEMENTED |
| `server/discover` | Use where peer supports | NOT IMPLEMENTED |
| Tool discovery/schema validation | Required | NOT IMPLEMENTED |
| Resource discovery/read | Required where used | NOT IMPLEMENTED |
| Tool call authorization | Required | NOT IMPLEMENTED |
| Timeouts/output limits | Required | NOT IMPLEMENTED |
| Result validation/provenance | Required | NOT IMPLEMENTED |
| `ttlMs`/`cacheScope` handling | Implement for 2026-07-28 peers | NOT IMPLEMENTED |
| Tasks extension | Optional; detect support | NOT IMPLEMENTED |
| Legacy protocol profiles | Only if required by a configured peer | NOT IMPLEMENTED |

**Implementation rules**
- Treat A2A and MCP as different layers. A2A delegates to agents; MCP authorizes tools/resources.
- Do not assume a permanent MCP transport session when integrating 2026-07-28 stateless peers.
- Do not assume all servers support the same extensions, authorization mechanism or tool set.
- Cache tool catalogs only with the peer's cache hints and invalidate when schema/version changes.
- Tool annotations are hints, not authorization. Server-side policy remains authoritative.
- Remote MCP URLs require SSRF controls, domain allowlists, DNS/IP checks, transport security, timeouts and response size limits.
- External MCP output is untrusted data and cannot override the platform policy.

## 3. Google Colab official MCP adapter

**Official server:** `https://colaboratory.googleapis.com/mcp`  
**Reference:** https://developers.google.com/colab/api/reference/mcp

| Tool | Documented purpose | Platform status |
|---|---|---|
| `list_runtimes` | List runtimes assigned to the requesting user | NOT INTEGRATED |
| `get_runtime` | Retrieve runtime specification and connection info | NOT INTEGRATED |
| `create_runtime` | Request a new runtime assignment | NOT INTEGRATED |
| `list_runtime_specs` | Inspect runtime configurations and user eligibility | NOT INTEGRATED |
| `create_session` | Create/get Jupyter kernel session on runtime | NOT INTEGRATED |
| `list_sessions` | List open sessions, including sessions opened outside MCP | NOT INTEGRATED |
| `execute_code` | Execute Python in runtime/session | NOT INTEGRATED |
| `delete_session` | Close session; discards kernel state, files on runtime persist | NOT INTEGRATED |
| `delete_runtime` | Delete runtime and associated sessions/state | NOT INTEGRATED |
| `get_subscription` | Inspect requesting user's Colab subscription tier | NOT INTEGRATED |

### Verified behavioral constraints

- A session groups calls that share Python kernel state.
- An execution can be made resumable with a stable UUID `executionId`; reattach using the identical request and same session.
- The documented streaming deadline is 600 seconds. A call that exceeds it returns `DEADLINE_EXCEEDED`; the same execution ID may be used to reattach before a terminal result is returned.
- stdout and stderr stream incrementally and are also returned aggregated.
- Cancellation uses the standard MCP `notifications/cancelled` flow and interrupts the kernel.
- The current `execute_code` tool returns text output only. Images, plots and widgets are not returned as rich outputs; oversized output is truncated and flagged.
- Deleting a session discards in-kernel variables/imports; files written to runtime disk persist until runtime deletion.
- `get_runtime` exposes connection information for standard Jupyter REST API/client use. Any richer-output adapter must be independently tested; it is not implied by the text-only MCP tool.
- Reuse eligible runtimes where possible; runtime creation is rate-limited. Delete a runtime only on explicit user request or a documented resource-limit recovery case.
- A Colab runtime is an external compute environment, not the platform's hostile-code sandbox.

### Authentication

Google's remote MCP authentication guidance supports user, application/workload or agent identities, depending on client and server support. Google remote MCP servers do not support Dynamic Client Registration or OAuth Client ID Metadata Documents. OAuth client ID/secret or Authorization bearer token flows may be used as supported by the client. Colab runtime APIs document `https://www.googleapis.com/auth/colaboratory` and read-only `https://www.googleapis.com/auth/colaboratory.readonly` scopes. See:
- https://docs.cloud.google.com/mcp/set-up-authentication-mcp-servers
- https://developers.google.com/colab/api/reference/rest/v1beta/runtimes/list
- https://developers.google.com/colab/api/reference/rest/v1beta/runtimespecs/list

**Acceptance boundary:** Colab connect/create/list, create session, execute, streamed text output, execution ID recovery, cancellation, disconnection/re-expiry, quota errors and user consent must be tested against an authorized real account. Do not promise notebook editor synchronization. Rich outputs are a separate integration requirement.

## 4. GitHub integration

**Preferred identity:** a GitHub App installed only on selected repositories with minimum repository permissions.

GitHub Apps start with no permissions by default. The selected permissions determine accessible APIs and events. Installation tokens can be limited to selected repositories and permission subsets; current docs describe a one-hour token lifetime. Access to modify `.github/workflows` requires the additional Workflows permission.

| Operation | Target permission policy |
|---|---|
| Repository listing/metadata | Metadata: read |
| Browse files/tree/commits | Contents: read |
| Branch and diff inspection | Contents: read |
| Pull request inspection | Pull requests: read |
| Create feature branch/commit in approved repo | Contents: write, only when approved |
| Create draft PR | Pull requests: write, only when approved |
| Read Actions run/check results | Actions: read |
| Modify workflow definitions | Workflows permission only if explicitly required |
| Merge protected branch/deploy | Separate action-bound human approval; no default agent permission |

Do not use a personal access token as the product's shared integration credential. Do not grant Administration permission by default. The product integration has not yet been created or tested.

Official references:
- https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app
- https://docs.github.com/en/rest/apps/apps

## 5. Supabase integration

Supabase is the proposed managed Postgres/auth/storage control plane. No project reference, schema, migration, credential or RLS policy was found in the repository.

| Workspace operation | Default policy |
|---|---|
| Project/config inspection | Read-only |
| Schema/table/index inspection | Read-only |
| RLS policy inspection | Read-only |
| Query explain/read analysis | Read-only |
| Generate migration proposal | Draft only |
| Apply migration to local/test DB | Controlled test execution |
| Apply migration to staging | Explicit approval + backup/recovery plan |
| Apply production migration | Critical approval + tested rollback/recovery |
| Change auth/RLS/storage policy | High risk; independent security review + approval |

For every exposed table, enable RLS, define grants and per-operation policies, and add positive and negative SQL tests. Schema changes must be version-controlled migrations. Secret/service-role keys must stay on backend/worker only; never expose them in the browser or shipped Android package.

Official references:
- https://supabase.com/docs/guides/database/postgres/row-level-security
- https://supabase.com/docs/guides/deployment/database-migrations
- https://supabase.com/docs/guides/database/secure-data

## 6. External integration test gate

Every adapter must pass:
- connection/authentication and token expiry;
- permission denial and tenant isolation;
- discovery/schema drift;
- timeouts and retry/idempotency;
- cancellation;
- malformed and oversized responses;
- provenance/audit logging;
- revocation and disconnection;
- recovery after worker restart;
- no secret leakage in frontend, notebook output, logs, artifacts or agent messages.

Until these tests have real service evidence, the status remains **NOT VERIFIED**.
