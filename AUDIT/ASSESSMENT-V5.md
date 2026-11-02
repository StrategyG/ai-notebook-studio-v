# AI Notebook Studio V5 — Institutional Baseline Assessment

**Assessment date:** 2026-11-02  
**Source archive:** `AI-Notebook-Studio-V5-APK-Project (1).zip`  
**Repository branch:** `production-hardening-v1`  
**Assessment scope:** Static source/archive review, repository tree inspection, protocol-documentation review and observed GitHub Actions output. No user-owned external service credentials or deployed runtime were tested.

## Executive result

- **Platform production-readiness estimate: 2.8/10.**
- **UI presentation maturity: 6.5/10.**
- **Android security/build foundation: materially improved, but not a complete platform.**
- **Release decision: NO-GO.**

The 9.0–9.3/10 figure in the product brief is a target, not an existing score. Scores in this document are engineering estimates and must be raised only by implementation and evidence.

## What the supplied source contains

The ZIP contains 13 files: Gradle configuration, Android manifest, two Kotlin activities, Android layouts/resources, and two standalone HTML artifacts. The main HTML is approximately 269 KB and the docs portal approximately 239 KB. There is no React source project, package manifest, TypeScript tree, backend, database migration, worker, or deployment descriptor in the ZIP.

The main UI is a bundled React presentation artifact with ten visible workspace concepts. Static inspection found no operational fetch/Axios/XMLHttpRequest/WebSocket/EventSource/localStorage/IndexedDB integration in the main UI. Static connection indicators, agent counts, cost figures and quality scores are therefore not treated as production telemetry.

## Original P0 security issues

The original Android WebView enabled JavaScript together with file-URL cross-origin access, file/content access and `MIXED_CONTENT_ALWAYS_ALLOW`. The original manifest allowed cleartext traffic and Android backup. Its navigation callback did not implement the intended allowlist. The manifest referenced launcher icons absent from the ZIP.

The hardening branch replaces the file origin with AndroidX WebViewAssetLoader, narrows local entry-point navigation, blocks non-local subresources, applies CSP, cancels SSL errors, disables file/content and cleartext access, disables backup, adds a native Demo/Offline disclosure, and supplies a missing-asset fallback.

## Current repository blockers

- The original `app/src/main/assets/index.html` and `docs.html` are still absent from the Git branch.
- Root `AI-Notebook-Studio-V5-React-Edition-FULL.html` is an 88-byte placeholder, not the supplied React bundle.
- The original React/TypeScript source project is not included.
- No application API/backend, AI provider gateway, BYOK vault, notebook persistence, Colab adapter, GitHub App, Supabase project schema, A2A gateway, MCP registry, agent orchestrator, policy engine or product observability service was found.
- No Gradle Wrapper, signed APK/AAB pipeline, device matrix or penetration-test evidence is present.

## Verified CI evidence on prior hardening commit

On commit `e135daae8d647b222aa3759df7411f235fcbab10`:
- Android CI run [41404503229](https://github.com/StrategyG/ai-notebook-studio-v/actions/runs/41404503229) passed unit tests, lint, debug APK assembly, unsigned release APK assembly and artifact upload. The deliberate final gate failed because the two required HTML files were absent.
- CodeQL run [41404503191](https://github.com/StrategyG/ai-notebook-studio-v/actions/runs/41404503191) succeeded using manual Gradle compilation.

These results prove only the Android build/static analysis path on that commit. They do not prove the app UI package is complete, no device test was run, and the release artifact is unsigned. Runs on the later documentation commit are in progress and must be evaluated separately.

## Baseline scorecard

| Dimension | Estimate / 10 |
|---|---:|
| Architecture completeness | 2.5 |
| Functional completeness | 1.5 |
| Security foundation | 6.0 |
| Reliability evidence | 3.0 |
| Performance evidence | 2.0 |
| Maintainability | 3.0 |
| AI quality/evaluation | 0.5 |
| Agent interoperability | 0.0 |
| UX/presentation | 6.5 |
| Operational readiness | 1.0 |
| **Overall platform readiness** | **2.8** |

## Required next work

1. Restore the original HTML assets and decide whether to recover or rebuild maintainable React source.
2. Implement the platform foundation: identity, tenant/project authorization, persistence, task/approval/artifact/audit contracts.
3. Implement real provider adapters and server-side credential management.
4. Implement canonical notebook documents and independently owned runtime state.
5. Integrate Colab through its documented MCP interface; do not treat it as a sandbox.
6. Implement GitHub App and Supabase adapters with least privilege, RLS and migrations.
7. Implement separate A2A agent delegation and MCP tool authorization layers.
8. Add isolated repository execution, acceptance tests, observability, backup/restore and signed release process.

See [Stage 0 baseline audit](../docs/STAGE-0-BASELINE-AUDIT.md), [target architecture](../docs/PLATFORM-ARCHITECTURE-V5.md), [protocol/integration matrix](../docs/PROTOCOL-INTEGRATION-MATRIX.md), [acceptance tests](../docs/ACCEPTANCE-TEST-PLAN.md), [roadmap](../docs/IMPLEMENTATION-ROADMAP-V5.md) and [threat model](../docs/SECURITY-THREAT-MODEL-V5.md).
