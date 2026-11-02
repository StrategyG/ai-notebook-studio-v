# Security policy

## Reporting a vulnerability
Do not publish secrets, API keys, personal data, or exploit details in public issues. Use GitHub private vulnerability reporting for this repository where enabled, or contact the repository maintainer privately.

## Client security boundary
- Never embed provider API keys, Supabase service-role keys, GitHub tokens, OAuth secrets, or signing keys in HTML, source control, build configuration, BuildConfig, or the APK.
- Do not register a JavaScript interface for untrusted WebView content.
- Serve bundled pages through AndroidX WebViewAssetLoader; never re-enable `file://` access or file-URL cross-origin access.
- Keep cleartext HTTP, mixed content, DOM storage, third-party cookies, popups, and geolocation disabled unless a reviewed requirement justifies a narrowly scoped change.
- The current offline/demo app has no INTERNET permission. Its CSP denies all network connections and non-bundled resource requests are blocked.
- Keep the app-assets URL allow-list limited to explicit local entry points. Non-HTTP(S) schemes must remain blocked and TLS certificate errors must never be bypassed.
- Keep Android backup disabled until credential and notebook export/restore behavior is reviewed.
- A future backend must enforce authentication, object-level authorization, tenant isolation, validation, quotas, audit logging, revocation, and abuse controls server-side.

## Release security checklist
1. Restore and review the exact bundled HTML assets; inspect scripts/dependencies and verify CSP compatibility.
2. Run Android CI, CodeQL, dependency/SBOM scans, secret scanning, and review all high/critical findings.
3. Threat-model API key handling, OAuth, notebook execution, file import/export, and cross-tenant data access.
4. Test WebView navigation, TLS error handling, backup behavior, and all critical flows on supported Android versions.
5. Use protected signing secrets outside Git; verify signed AAB provenance and staged rollout/rollback.
