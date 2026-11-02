# ADR-0001: Start with a Modular Monolith

- **Status:** Proposed
- **Date:** 2026-11-02
- **Decision owners:** Platform Architecture / Security / SRE

## Context

The repository currently contains only an Android WebView shell and bundled frontend artifacts. There is no deployed API, queue, worker fleet, database schema or external integration service. Creating multiple independently deployed microservices immediately would add network, authentication, deployment and observability complexity before domain boundaries have been proven.

## Decision

Start with one backend modular monolith (proposed Python/FastAPI) with explicit modules and ports/adapters. Run background work in a separately constrained worker process from the same codebase. Keep the web client React/TypeScript and the existing Android shell as a client surface, not as a backend host.

Keep domain modules and contracts separately testable:
- identity/access;
- projects/workspaces;
- conversations/providers;
- notebooks/runtimes;
- repository/database integrations;
- agents/tasks/orchestration;
- approvals/audit/artifacts;
- MCP/A2A gateways.

Use Postgres/Supabase as the initial durable data store, versioned SQL migrations and RLS. Use transactional outbox plus SSE for event delivery. Introduce a separate broker or service only when load, failure isolation, security or SLO evidence requires it.

## Consequences

**Positive**
- Fewer deployments and simpler CI/operations at initial scale.
- Strong typing/validation and explicit module boundaries remain possible.
- Easier transaction handling for task state, approvals, audit and outbox.
- Protocol adapters can evolve independently from the domain model.

**Trade-offs**
- The API process must be carefully isolated from long-running or untrusted execution.
- Module boundaries must be enforced through dependency rules and tests.
- Background worker and API release may initially share one version cadence.

## Revisit when

- A worker requires independent scaling or stronger host isolation.
- Provider/runtime calls threaten API reliability.
- A module requires a different security boundary or uptime SLO.
- Team ownership or deployment cadence diverges enough to justify extraction.

## Rejected alternatives

- **Microservices from day one:** unjustified operational complexity without traffic, ownership or scaling evidence.
- **One large unrestricted application module:** weakens domain, permission and testing boundaries.
- **Agents as independent services by default:** agent identity/capability can be isolated in-process first; externalization is a deployment choice, not a protocol requirement.
