# Stage 0 — Discovery and Baseline Audit

**Snapshot date:** 2026-11-02  
**Repository:** StrategyG/ai-notebook-studio-v  
**Reviewed branch:** production-hardening-v1  
**Source archive:** AI-Notebook-Studio-V5-APK-Project (1).zip  
**Review mode:** Static archive/repository inspection and observed GitHub Actions runs. No production credentials, live Google Colab runtime, Supabase project, or independently operated A2A agent was available for integration testing.

## 1. Executive decision

**Stage 0 static discovery: COMPLETE.**  
**Platform production status: NO-GO.**

The supplied source is an Android application shell containing two standalone HTML artifacts. The current Git branch adds a substantially safer Android WebView boundary and CI, but the complete HTML artifacts are not yet checked into the branch. No application backend, provider gateway, durable notebook service, external runtime adapter, GitHub App integration, Supabase schema, MCP client/registry, A2A gateway, or multi-agent orchestrator was found.

The existing UI is a presentation prototype, not evidence of operational integrations. Product labels such as connected, healthy, agent count, cost, and quality score are not trusted as telemetry unless backed by a real service response with provenance and timestamp.

## 2. Source archive inventory

The ZIP contains 13 files:

| Source | Size | Observed role |
|---|---:|---|
| `build.gradle` | 164 B | Android Gradle plugin 8.2.0 / Kotlin 1.9.10 |
| `settings.gradle` | 338 B | Single Android module |
| `gradle.properties` | 114 B | AndroidX and basic Gradle configuration |
| `README.md` | 1,131 B | Install/build guide and prototype claims |
| `app/build.gradle` | 1,093 B | Android app module, minSdk 24 / targetSdk 34 |
| `app/src/main/AndroidManifest.xml` | 1,177 B | Original permissions, icon references and app policy |
| `app/src/main/assets/index.html` | 268,617 B | Single-file React UI artifact |
| `app/src/main/assets/docs.html` | 238,847 B | Single-file documentation portal |
| `MainActivity.kt` | 2,114 B | Original WebView host |
| `DocsActivity.kt` | 606 B | Original documentation WebView |
| `activity_main.xml` | 347 B | WebView layout |
| `strings.xml` | 84 B | Minimal Android strings |
| `colors.xml` | 65 B | Minimal Android colors |

Neither the ZIP nor the inspected repository contains a Gradle Wrapper. The ZIP does not contain a React source project, `package.json`, TypeScript source tree, Vite configuration, backend source, database migrations, or service deployment manifests.

## 3. Frontend evidence

- The main HTML title is the generic `React Artifact`.
- The HTML files contain inline bundled scripts and CSS. They are deliverable artifacts, not a maintainable React source project.
- Both files include a viewport meta tag. The main UI has CSS breakpoints at 640, 768, 1024 and 1280 px; the docs portal has breakpoints at 640, 768 and 1024 px.
- Static inspection of `index.html` found no `fetch(`, Axios, XMLHttpRequest, constructed WebSocket, EventSource, localStorage, sessionStorage or IndexedDB implementation.
- The docs portal contains protocol names, code examples and diagrams. Those references are specifications/content, not implemented clients.
- Google Fonts URLs are referenced by the supplied HTML. Therefore the original README's “Offline 100%” claim is not literally true for the same visual typography. The hardened Android CSP blocks remote resources; system font fallback is expected until fonts are bundled locally.
- No browser/device viewport matrix or visual-regression evidence was supplied.

## 4. Original Android security findings

The original Android shell enabled JavaScript and DOM storage alongside file access, content access, file-URL cross-origin access and `MIXED_CONTENT_ALWAYS_ALLOW`. The original manifest enabled cleartext traffic and Android backup. The original main-frame URL callback did not enforce its apparent local/external URL policy. The manifest referenced launcher resources absent from the ZIP.

These original settings were replaced on `production-hardening-v1` with AndroidX WebViewAssetLoader, stricter navigation checks, local asset CSP, blocked non-local requests, SSL-error cancellation, disabled file/content access, disabled cleartext and backup, a launcher vector, a native Demo/Offline banner, and a missing-asset fallback.

The hardened Android shell remains a client container only. Its current offline CSP and absence of INTERNET permission intentionally prevent live API integrations until a separately reviewed online configuration is designed.

## 5. Repository state

At the reviewed branch head:
- Android project and hardening resources are present.
- Unit tests for the app-assets URL policy are present.
- Android CI, CodeQL and Dependabot workflows are present.
- `app/src/main/assets/index.html` and `docs.html` are absent.
- Root file `AI-Notebook-Studio-V5-React-Edition-FULL.html` is an 88-byte placeholder, not the full React application.
- No `apps/web`, `apps/api`, worker, shared contracts, Supabase migrations, A2A gateway, MCP registry, provider adapter, or notebook persistence source tree is present.

## 6. Verified CI evidence

On commit `e135daae8d647b222aa3759df7411f235fcbab10`:

- Android CI run [41404503229](https://github.com/StrategyG/ai-notebook-studio-v/actions/runs/41404503229): unit tests PASS, lint PASS, debug APK assembly PASS, unsigned release APK assembly PASS, artifact uploads PASS; final required-HTML-assets gate FAIL.
- CodeQL run [41404503191](https://github.com/StrategyG/ai-notebook-studio-v/actions/runs/41404503191): Kotlin/Android analysis workflow SUCCESS after changing to manual Gradle compilation.
- The APKs from this CI path are validation artifacts only. The release APK is unsigned; the UI assets are missing; there has been no device test.

These runs verify the Android foundation's build and static-analysis path only. They do not verify AI, notebook execution, integrations, A2A/MCP, security certification, or production operations.

## 7. Baseline status matrix

| Capability | Status | Evidence / gap |
|---|---|---|
| Android WebView hardening | PARTIAL | Source change and CI build evidence; no device/penetration test |
| Responsive visual layout | NOT VERIFIED | Viewport tags and CSS breakpoints exist; no Playwright/browser matrix |
| AI Chat/provider routing | NOT IMPLEMENTED | No provider adapter or API route found |
| BYOK/secret vault | NOT IMPLEMENTED | No secret storage or key lifecycle service |
| Notebook document model | NOT IMPLEMENTED | No durable notebook schema/version store |
| Colab MCP adapter | NOT IMPLEMENTED | No Google OAuth or MCP client |
| GitHub Workspace | NOT IMPLEMENTED | No product GitHub App/OAuth integration |
| Supabase Workspace | NOT IMPLEMENTED | No Supabase adapter, migration, or RLS proof |
| Repository Engineer | NOT IMPLEMENTED | No product repository analysis/patch workflow |
| Testing and Quality Center | NOT IMPLEMENTED | Android tests/CI exist; no platform-level QA suite |
| Agent registry/orchestrator | NOT IMPLEMENTED | Static dashboard only |
| A2A | NOT IMPLEMENTED | No Agent Card or A2A endpoint/client |
| MCP | NOT IMPLEMENTED | No MCP client/server registry or policy enforcement |
| Governance/approvals/audit | NOT IMPLEMENTED | No backend policy/approval/audit model |
| Operational observability | NOT IMPLEMENTED | No service logs, metrics, traces, alerts or SLOs |

## 8. Initial quality scorecard

These are conservative engineering estimates against the supplied institutional platform specification, not test results or a certification.

| Dimension | Baseline estimate |
|---|---:|
| Architecture completeness | 2.5/10 |
| Functional completeness | 1.5/10 |
| Security foundation | 6.0/10 |
| Reliability evidence | 3.0/10 |
| Performance evidence | 2.0/10 |
| Maintainability | 3.0/10 |
| AI quality/evaluation | 0.5/10 |
| Agent interoperability | 0.0/10 |
| UX/presentation | 6.5/10 |
| Operational readiness | 1.0/10 |

**Overall platform readiness estimate: 2.8/10.** The visual prototype is more mature than the product system behind it. The score will only increase when capabilities are implemented and independently exercised.

## 9. Release decision

**NO-GO.** Required blockers include restoring the two original UI assets, establishing a maintainable source project, building real backend/provider and data services, verifying Colab/GitHub/Supabase integrations, enforcing agent and tool authorization, implementing isolated execution, and completing device/security/operational tests plus signed release engineering.

## 10. Official references reviewed

- A2A specification, latest released version 1.0.0: https://github.com/a2aproject/A2A/blob/main/docs/specification.md
- A2A official SDKs: https://a2a-protocol.org/latest/sdk/
- MCP specification release 2026-07-28: https://blog.modelcontextprotocol.io/posts/2026-07-28/
- Google Colab MCP reference: https://developers.google.com/colab/api/reference/mcp
- Google Colab execute_code reference: https://developers.google.com/colab/api/reference/mcp/tools_list/execute_code
- Google MCP authentication: https://docs.cloud.google.com/mcp/set-up-authentication-mcp-servers
- GitHub App permission selection: https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app
- Supabase RLS: https://supabase.com/docs/guides/database/postgres/row-level-security
- Supabase database migrations: https://supabase.com/docs/guides/deployment/database-migrations
