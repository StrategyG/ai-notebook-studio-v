# AI Notebook Studio V5.1 — hardened Android demo shell

Branch: `production-hardening-v1` · Current status: **NO-GO for production release**

This repository branch hardens the Android WebView shell and its build pipeline. It is not yet the complete V5 application: the original `app/src/main/assets/index.html` and `docs.html` from the supplied source ZIP are still absent from this branch. The app therefore shows a safe missing-asset message until those exact files are restored.

## What is implemented

- AndroidX `WebViewAssetLoader` serves the two local entry points from the reserved app-assets HTTPS origin.
- File/content access, file-URL cross-origin access, mixed content, DOM storage, third-party cookies, popups, geolocation, and arbitrary URI schemes are disabled.
- A restrictive Content Security Policy blocks all network connections, frames, forms, objects, and remote scripts/styles; only bundled UI scripts/styles and local/data/blob images are allowed.
- Non-bundled WebView requests are blocked. User-clicked HTTP(S) links open in the system browser; SSL failures are canceled.
- No JavaScript-to-native bridge is registered. The manifest has no INTERNET permission in this offline demo mode.
- Android backup and cleartext HTTP are disabled. A native **DEMO / OFFLINE** banner warns that UI connection states and displayed data are simulated.
- Main screen has a useful missing-asset error state and explicit Docs navigation.
- JUnit navigation-policy tests; Android CI for unit tests, lint, debug APK, and unsigned release build validation.
- CodeQL and Dependabot workflows are configured.

## Build locally

Requirements: JDK 17, Android SDK 35, and Gradle 8.9. This repository currently does not include the Gradle Wrapper.

```bash
gradle testDebugUnitTest lintDebug assembleDebug assembleRelease
```

The release build from CI is **unsigned validation only**. Debug and unsigned release artifacts are useful for engineering validation but are not publishable production APK/AABs.

## Product functionality — not connected yet

The frontend is a static/demo UI. No operational AI provider adapter, model execution service, secure BYOK vault, user authentication, GitHub OAuth, notebook persistence, cloud sync, or notebook kernel/runtime has been verified or implemented. Labels such as connected, agents, costs, and task states in the original UI must not be treated as live service status.

Do not place API keys, GitHub tokens, Supabase service-role keys, OAuth secrets, or signing credentials in the APK or frontend bundle.

## Release blockers

1. Restore and verify the exact `index.html` and `docs.html` source assets in the Git branch.
2. Implement and security-review real backend/provider execution, authentication/authorization, secure credential handling, persistence, and notebook runtime.
3. Add WebView/device instrumentation tests and test critical user flows on supported Android versions.
4. Add a Gradle Wrapper, protected release signing, signed AAB generation, SBOM/dependency review, and staged release verification.
5. Require passing Android CI and CodeQL on the exact release commit.

See [Production Readiness](docs/PRODUCTION_READINESS.md), [Technical Evaluation](docs/TECHNICAL_EVALUATION.md), and [Security Policy](SECURITY.md).


## V5.0 institutional transformation documents

The engineering transformation is being developed in explicit stages. The Stage 0 baseline, target architecture, protocol/integration matrix, acceptance tests, implementation roadmap and threat model are documented here:

- [Stage 0 Baseline Audit](docs/STAGE-0-BASELINE-AUDIT.md)
- [Platform Architecture V5](docs/PLATFORM-ARCHITECTURE-V5.md)
- [Protocol and Integration Matrix](docs/PROTOCOL-INTEGRATION-MATRIX.md)
- [Acceptance Test Plan](docs/ACCEPTANCE-TEST-PLAN.md)
- [Implementation Roadmap](docs/IMPLEMENTATION-ROADMAP-V5.md)
- [Security Threat Model](docs/SECURITY-THREAT-MODEL-V5.md)
- [ADR-0001: Modular Monolith](docs/adr/0001-modular-monolith.md)

These are target specifications and audit deliverables, not claims that their proposed services are already implemented. Capability statuses remain explicit in the documents.
