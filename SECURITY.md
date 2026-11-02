# Security policy

## Supported release
Security fixes target the latest supported release on the default branch.

## Reporting a vulnerability
Do not publish secrets, API keys, personal data, or exploit details in public issues. Use GitHub's private vulnerability reporting for this repository where enabled, or contact the repository maintainer privately.

## Client security boundaries
- Never embed provider API keys, Supabase service-role keys, GitHub PATs, signing keys, or OAuth client secrets in HTML, source control, build configuration, or the APK.
- The Android WebView must not expose a JavaScript interface to untrusted content.
- Local HTML is served through `WebViewAssetLoader`; `file://` access and cleartext HTTP are disabled.
- External links are opened outside the WebView; non-HTTP(S) schemes are blocked.
- Any future backend must enforce authentication, authorization, tenant isolation, input validation, quotas, and audit logging server-side.

## Release checklist
Run CI, review dependency updates, scan the release artifact, verify signing provenance, and test on supported Android API levels before publishing.
