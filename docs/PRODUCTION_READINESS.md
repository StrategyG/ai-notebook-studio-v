# Production hardening plan — AI Notebook Studio

## Scope of this change
This change hardens the Android container and repository workflow. It does **not** convert the bundled frontend into a working AI backend. AI provider execution, secure BYOK management, user accounts, cloud sync, GitHub OAuth, notebook database persistence, and multi-tenant authorization remain separate engineering workstreams.

## Implemented in this branch
- Replaced broad `file://` WebView loading with AndroidX `WebViewAssetLoader` on the reserved app-assets HTTPS origin.
- Disabled file/content access, cleartext traffic, mixed content, geolocation, automatic popups, and WebView multiple windows.
- Added an external-navigation policy: app-assets remain in-app; HTTP(S) links open in the browser; other schemes are blocked.
- Added SSL error cancellation and main-frame load error feedback.
- Removed the long-press-to-open-docs gesture; added an explicit Docs control.
- Added WebView state save/restore and cleanup.
- Disabled Android backup until a reviewed user-data export/restore policy exists.
- Added network security configuration, app icon vector, release minification/resource shrinking, Android SDK 35 / Java 17 build settings, and CI for unit tests, lint, and debug assembly.

## Not yet production complete
1. **AI execution:** implement a server-side provider gateway or carefully scoped BYOK design. Do not put API secrets in the APK or WebView JavaScript bundle.
2. **Credential security:** Android Keystore-backed encryption for local user secrets; server-side secret vault for hosted credentials; rotation and revocation.
3. **Persistence:** Room/SQLite schema, migrations, encryption decisions, export/import, conflict handling, and backup consent.
4. **Identity and access:** OAuth authorization-code + PKCE or a GitHub App; least privilege; backend token exchange; session expiry and revocation.
5. **Backend:** authenticated API, authorization checks on every object, rate limiting, quotas, audit events, abuse protection, and operational monitoring.
6. **Frontend hardening:** audit the bundled HTML dependencies, add a restrictive Content Security Policy compatible with its runtime, remove unused packages, and verify all external resource origins.
7. **Quality:** instrumentation tests on API 24/current Android, WebView navigation tests, accessibility checks, crash/ANR monitoring, dependency/SBOM scanning, and security testing.
8. **Release:** generate a Gradle wrapper, configure protected signing secrets in CI, build signed AAB, verify Play policy requirements, and publish through staged rollout.

## Release gate
Do not label a release production-ready until CI passes on the exact release commit, signed AAB is reproducible, the security review is complete, critical user flows are tested, and the backend/data controls above are implemented. The current branch is a hardened Android foundation, not a production-certified AI platform.
