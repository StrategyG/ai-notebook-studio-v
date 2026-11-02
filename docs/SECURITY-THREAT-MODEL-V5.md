# AI Notebook Studio V5 — Initial Security Threat Model

**Version:** 0.1 baseline  
**Status:** Design review draft; no production backend exists to test.

## 1. Assets to protect

- User identity, sessions, project membership and OAuth grants.
- AI provider keys, GitHub credentials, Google credentials and Supabase secrets.
- Notebook source, conversation context, runtime results and private artifacts.
- Repository content, proposed diffs, pull requests and CI metadata.
- Supabase schema, row data, RLS policies and migration history.
- Agent identities, capabilities, delegated tasks and tool permissions.
- Approval records, audit history and release artifacts.

## 2. Trust boundaries

1. Browser/mobile client → application API.
2. Tenant/project boundary → shared application database.
3. Orchestrator/agent → MCP tool gateway.
4. Internal platform → external A2A agent.
5. Application API → AI provider.
6. Application → Colab user runtime.
7. Repository worker → untrusted repository code.
8. Application → GitHub App / Supabase management interfaces.
9. Artifact store → browser/agent download.

Every boundary requires identity, authorization, validation, resource limits, provenance and auditable failure handling.

## 3. High-priority threats and controls

| Threat | Risk | Required controls |
|---|---|---|
| Prompt injection in repository/docs/tool results | Agent takes instructions from untrusted content | Mark content untrusted, separate policy from context, tool allowlists, approvals, injection evaluation |
| Confused deputy / privilege escalation | Agent uses its service identity to exceed user's authority | Effective permission = user grant ∩ project scope ∩ task scope ∩ agent capability ∩ tool policy |
| Cross-tenant object access / IDOR | Notebook/artifact/task exposed across tenants | Tenant ID on domain records, object-level API checks, RLS, negative integration tests |
| Secret leakage | Keys in frontend, logs, agent messages, notebook output or artifacts | Backend-only vault, envelope encryption, redaction, short-lived tokens, scan outputs and logs |
| Malicious Agent Card or MCP server | SSRF, tool poisoning, hostile schemas | Peer allowlist/approval, HTTPS, URL/DNS/IP validation, schema bounds, version pinning, output validation |
| Replay/duplicate task messages | External write executed twice | Idempotency keys, signed request metadata where supported, replay window, dedupe store |
| Malicious repository code | Host escape, data theft, lateral network access | Disposable isolation, non-root, read-only base image, CPU/memory/time limits, egress deny-by-default, no host secrets |
| Destructive production DB operation | Loss/corruption of data | Read-only default, migration review, staging tests, backup/recovery proof, exact approval |
| Unauthorized branch merge/deploy | Unreviewed code reaches production | Branch protection, feature branch only, draft PR default, explicit action-bound approval |
| Artifact substitution | Reviewer approves one file but different content is delivered | SHA-256/content digest, immutable artifact versions, provenance and review binding |
| Runtime disconnect/expiry | Notebook task silently lost or corrupt | Runtime and execution states separate; persist notebook source first; resumable execution ID where supported; recovery tests |
| Resource exhaustion/cost runaway | Agent loop or provider/runtime abuse | Deadline, concurrency quotas, delegation depth, retries, cost ceiling, output size limit and circuit breakers |
| Audit tampering | Evidence of privileged action removed | Append-oriented event store, restricted writer, export/retention and tamper-evidence checks |

## 4. Required authorization rule

The agent cannot grant itself or another agent new privileges. A task's permissions are fixed at assignment and revalidated at tool-call time. A2A peer identity does not imply permission to call MCP tools.

## 5. Approval binding

An approval record must bind:
- approving actor and role;
- exact target project/repository/database/runtime;
- exact action and risk;
- diff/migration/artifact SHA-256;
- preconditions and expected effect;
- approval expiry and one-time/limited-use nonce;
- execution result and resulting commit/migration/runtime reference.

Any changed diff, target, scope or expiry invalidates the approval and requires a new decision.

## 6. Isolation policy

Colab is not approved as a sandbox for hostile repository code. The repository engineering path must use an independently controlled ephemeral execution boundary. When that boundary is unavailable, mark the task BLOCKED rather than falling back to the user's Colab runtime.

## 7. Current security evidence

- Android WebView hardening is present in the review branch and has CI build evidence.
- CodeQL has passed on the current hardening baseline.
- No production backend, API authorization, agent identity, MCP tool gateway, Colab credentials, GitHub App, Supabase project, notebook store or repository sandbox exists in the reviewed source.
- Therefore backend/tenant/agent/runtime threat controls remain **NOT IMPLEMENTED / NOT VERIFIED**.

## 8. Required next security activities

1. Data-flow diagram and secret classification.
2. STRIDE review for API, A2A, MCP, Colab and GitHub boundaries.
3. Abuse-case tests for cross-tenant access, confused deputy, prompt injection, replay and SSRF.
4. Sandbox threat model and escape/network tests.
5. Supabase RLS negative tests for every table/operation.
6. Release threat review and independent penetration test before production.
