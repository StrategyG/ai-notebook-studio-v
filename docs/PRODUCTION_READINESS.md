# Production readiness — AI Notebook Studio

**Decision: NO-GO for a production release.** This branch is an Android security-hardening and CI foundation for an offline/demo frontend, not a production AI notebook service.

## Implemented in `production-hardening-v1`

- AndroidX WebViewAssetLoader with an HTTPS app-assets origin; no `file://` loading.
- File/content access, file-URL cross-origin access, mixed content, DOM storage, third-party cookies, geolocation, automatic popups, and multiple windows disabled.
- CSP applied to local HTML: no network connections, frames, forms, objects, workers, remote scripts or remote styles. Inline script/style remain enabled only because the supplied single-file React UI requires them.
- All requests not served by the local asset loader are blocked; clicked HTTP(S) navigations are handed to the system browser; unknown schemes and SSL errors are rejected.
- No JavaScript bridge; INTERNET permission removed for this offline-only frontend.
- Android backup and cleartext traffic disabled; network security configuration and launcher vector resource added.
- Explicit Docs button; Demo/Offline disclosure banner; fallback error UI if the required HTML assets are not packaged.
- Unit tests for local URL allow-listing, including scheme/host/path/port/user-info/traversal cases.
- CI configured for tests, lint, debug APK, unsigned release build, and artifact uploads. CodeQL and Dependabot automation configured.

## CI evidence observed

Workflow run [41402980821](https://github.com/StrategyG/ai-notebook-studio-v/actions/runs/41402980821) completed these steps successfully:
- Unit tests
- Android lint
- Debug APK assembly
- Unsigned release APK assembly (R8/resource shrink validation)
- Debug and unsigned release artifact uploads

The final asset-integrity step failed because the branch does not yet contain the original `index.html` and `docs.html` files. The APK artifacts from that run are not complete V5 application builds and are not signed for distribution. Later CI/CodeQL runs are being used to verify subsequent workflow changes; inspect the Actions page for their exact outcomes.

## Blocking work before production

### 1. Restore frontend source assets
The supplied ZIP contains `app/src/main/assets/index.html` and `app/src/main/assets/docs.html`. They must be added byte-for-byte, checked into the repository, reviewed, and included in the Android package. Until then the UI entry points do not load.

### 2. Real AI service and provider integration
- Build an authenticated provider gateway or a deliberately scoped BYOK implementation.
- Provider keys must never be embedded in HTML, APK resources, BuildConfig, or source control.
- Add timeouts, retry/backoff, usage budgets, rate limits, model capability allow-lists, and safe error handling.
- Distinguish provider connection state from local UI/demo state.

### 3. Identity, security, and data
- OAuth authorization-code + PKCE or a GitHub App with least privilege and server-side token exchange.
- Object-level authorization, tenant isolation, request validation, audit trail, abuse controls, revocation, and session expiry.
- Keystore-backed local encryption for device-held secrets; managed vault and rotation for hosted credentials.
- Room/database schema, migrations, notebook persistence, export/import, conflict resolution, and explicit backup/retention policy.

### 4. Notebook execution and reliability
- Implement isolated notebook/kernel execution with CPU, memory, process, filesystem, and network limits; never execute untrusted user code inside the Android app process.
- Add durable job state, cancellation, idempotency, queue limits, and execution logs.
- Add crash/ANR telemetry, health checks, monitoring, alerting, and documented incident recovery.

### 5. Verification and release engineering
- Restore frontend assets and add instrumentation/WebView tests and device coverage for supported Android API levels.
- Accessibility, performance, privacy, threat-model, dependency/SBOM, and penetration testing.
- Commit Gradle Wrapper files and pin the wrapper distribution checksum.
- Configure protected signing secrets outside the repository; generate and verify a signed AAB; add release provenance and staged rollout/rollback.

## Release gate

Do not change the status to production-ready until the original UI assets are committed, real backend functionality and data protections are implemented, all critical flows pass tests, security review finds no unresolved critical/high issues, Android CI and CodeQL pass on the exact release commit, and a signed AAB has been verified on target devices.
