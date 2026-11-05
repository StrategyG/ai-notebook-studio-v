# AI Notebook Studio ↔ UGAI task integration v1

**Status:** implementation candidate; live identity-provider acceptance is pending.

## Ownership boundary

- Notebook authenticates the user, checks active tenant membership and application role, and presents task status.
- UGAI remains the authority for task creation, state transitions, idempotency and workflow execution.
- IM19 remains the only central MCP gateway. Notebook does not call upstream MCP servers or hold connector credentials.

## Request path

```text
Notebook UI
  → Notebook API: verify user + active tenant role
  → identity provider: RFC 8693 token exchange (server-to-server)
  → UGAI API: verify exchanged token + project membership
  → durable PostgreSQL task store
  → Notebook API: poll authoritative task projection
```

The Notebook API sends the authenticated user's bearer token only to the
configured identity token-exchange endpoint. The UGAI client secret is used
only for client authentication to that endpoint. The resulting short-lived
UGAI-audience token is sent only to UGAI. Neither token is returned to the
browser or written into task payloads, logs or audit fields.

## Task routes and authorization

| Route | Required Notebook database role | UGAI scope |
|---|---|---|
| `POST /api/v1/tasks` | `agents:run` | `ugai:tasks:write` |
| `GET /api/v1/tasks/{task_id}` | `notebooks:read` | `ugai:tasks:read` |
| `POST /api/v1/tasks/{task_id}/cancel` | `agents:run` | `ugai:tasks:cancel` |

The request model rejects additional fields. Tenant, actor and roles are not
accepted from the client body. UGAI derives identity from the exchanged
verified token and enforces the project allowlist independently. Active
membership and permissions are checked from Notebook's database before
token exchange and task forwarding.

## Version 1 status vocabulary

`queued`, `running`, `awaiting_approval`, `awaiting_clarification`,
`blocked`, `outcome_unknown`, `succeeded`, `failed`, `cancelled`.

UGAI internal stages are projected onto this public vocabulary by UGAI.
Notebook must not invent aliases or independently infer terminal state.
Cancellation of a running stage is rejected until the worker supports
cooperative cancellation. `outcome_unknown` requires reconciliation.

## Retry and idempotency

Notebook never automatically retries a task-creation POST after a transport
failure. A lost response is ambiguous: the task may already exist. Re-submit
only with the exact same idempotency key and identical request payload.
UGAI returns the original task for a matching replay and HTTP 409 for a
same-key/different-payload conflict.

## Production acceptance still required

1. Configure a real RFC 8693 token-exchange client and UGAI token audience.
2. Verify exact issuer, signing algorithm, audience, tenant claim, user subject,
   tenant roles and project-membership claim through live staging identities.
3. Prove users with viewer/member/editor/admin roles receive the correct
   route permissions from database membership, not JWT role claims.
4. Prove cross-tenant and unauthorized project requests are denied by both
   Notebook and UGAI.
5. Run submit → restart UGAI API → poll task, idempotent replay, conflicting
   replay, cancellation and unknown-outcome tests against the isolated staging
   PostgreSQL service.
6. Prove a registered UGAI worker consumes the encrypted Notebook input and
   produces a durable result that Notebook can retrieve under the same tenant.
7. Validate token exchange failure, UGAI outage, expired token, key rotation,
   audit redaction, rate limiting and rollback.

This document is a release checklist, not evidence that a live IdP, staging
environment or production deployment has passed.
