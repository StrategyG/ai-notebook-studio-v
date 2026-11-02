# AI Notebook Studio V5 — Acceptance Test Plan

**Baseline date:** 2026-11-02  
**Status values:** PASS, FAIL, BLOCKED, NOT RUN, NOT VERIFIED, WARNING  
**Current decision:** NO-GO

No test below is marked PASS merely because a UI screen, code example, mocked response or documentation page exists.

## Acceptance matrix

| ID | Acceptance | Environment / preconditions | Expected result | Current status |
|---|---|---|---|---|
| AT-01 | Secure AI provider configuration and conversation | Authenticated test tenant; provider sandbox key; secret store | Key stored server-side, never returned to client/log; chat streams; budgets and failures are recorded | NOT RUN |
| AT-02 | Notebook create/edit/persist/export | Test database and browser | Cell order/content/version persist; export is valid .ipynb and re-import round-trips | NOT RUN |
| AT-03 | Real Colab execution and runtime state | Authorized Google identity, Colab MCP enabled | List/connect runtime, create session, execute code, stream text, report actual status and recover eligible execution | NOT RUN |
| AT-04 | Chat-to-Notebook collaboration | AT-01 and AT-02 | Chat generates a proposed cell patch; notebook user reviews/applies it; no silent overwrite | NOT RUN |
| AT-05 | GitHub inspection and controlled PR workflow | Test GitHub App installation on test repo | Read tree/diff, create isolated feature branch and draft PR only with approval; no protected branch push/merge | NOT RUN |
| AT-06 | Supabase inspection and migration governance | Disposable Supabase project | Read schema/RLS; generate migration; test locally; staging/production writes require approvals | NOT RUN |
| AT-07 | Repository audit/repair/test/evidence | Disposable repository and isolated sandbox | Root cause, evidence, diff, tests, security impact and rollback recorded; independent review | NOT RUN |
| AT-08 | Internal agent discovery and authenticated delegation | Agent registry and test agents | Discover capability-scoped agents; validate identity; scope task and permissions | NOT RUN |
| AT-09 | External A2A interoperability | Independent A2A 1.0 peer/SDK | Agent Card discovery, auth, task, message, status and artifact exchange pass compatibility suite | NOT RUN |
| AT-10 | MCP discovery and authorized tool execution | Controlled MCP test server | Discover schema, allowlisted tool call, output validation, per-call authorization and audit | NOT RUN |
| AT-11 | Multi-agent dependency management | At least 3 internal agents and task DAG | Parallel independent work; sequential dependencies; no cycles; bounded retry/delegation | NOT RUN |
| AT-12 | Unauthorized delegation/privilege escalation rejection | Adversarial tenant/agent fixtures | Cross-tenant, out-of-scope and elevated operations are denied and audited | NOT RUN |
| AT-13 | Prompt injection resistance | Malicious repo docs, tool output and remote agent artifacts | Embedded instructions remain untrusted data; cannot override policy or disclose secrets | NOT RUN |
| AT-14 | Duplicate/retry/recovery behavior | Fault injection and worker restart | Idempotency prevents duplicate side effects; interrupted tasks reconcile to authoritative state | NOT RUN |
| AT-15 | Artifact provenance and access | Two tenants, private artifacts | Content hash, owner/project scope and provenance validate; cross-tenant reads denied | NOT RUN |
| AT-16 | Responsive Android/tablet/laptop/desktop | Playwright + Android browsers/emulator | Required viewports render without critical clipping; keyboard, zoom and touch targets meet UX contract | NOT VERIFIED |
| AT-17 | Visual regression and interaction | Stable browser/OS versions and visual baselines | Workspace interactions pass; unexpected screenshot diffs are reviewed | NOT RUN |
| AT-18 | Observability/cost/recovery | Staging deployment and dashboards | Correlated trace from user request through task/agent/tool; budgets, error rates, backups and restore validated | NOT RUN |

## Required viewport matrix

Test all critical workspaces and navigation at these CSS viewport widths:

| Range | Representative widths | Current evidence |
|---|---|---|
| 320–359 px | 320, 359 | NOT RUN |
| 360–430 px | 360, 390, 430 | NOT RUN |
| 431–767 px | 480, 640, 767 | NOT RUN |
| 768–1023 px | 768, 900, 1023 | NOT RUN |
| 1024–1439 px | 1024, 1280, 1439 | NOT RUN |
| 1440 px+ | 1440, 1920 | NOT RUN |

The supplied HTML has viewport metadata and some CSS breakpoints. These are static implementation hints, not responsive test evidence.

## Test evidence record schema

Each execution must store:

- test_id and test_version;
- code commit and configuration digest;
- environment/browser/device/service version;
- authenticated test principal and scoped permissions (never raw tokens);
- preconditions and deterministic fixtures;
- start/end timestamps;
- exact test steps;
- expected and actual result;
- logs, traces, screenshots, diff and artifact references;
- pass/fail/blocked/not-run status;
- issue/owner and remediation commit.

## Release-blocking conditions

- Any unauthorized cross-tenant/object access.
- Secret leakage or privilege escalation.
- Untrusted code executed without the approved isolation boundary.
- Production write, merge or deployment without exact human approval.
- Critical data loss or unverified backup recovery.
- Failed critical acceptance test or unresolved critical/high security finding.
