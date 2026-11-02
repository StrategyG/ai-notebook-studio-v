# AI Notebook Studio V5.1 — Android hardening branch

This repository contains the Android WebView shell for AI Notebook Studio. Branch `production-hardening-v1` adds a safer WebView boundary, Android release defaults, launcher resources, and CI quality gates. **The original `index.html` and `docs.html` from the supplied ZIP are still not present in this repository**, so the app will not display its full V5 UI until those assets are added.

## Build locally

Requirements: Android Studio with Android SDK 35, JDK 17, and Gradle 8.9.

```bash
gradle testDebugUnitTest lintDebug assembleDebug
```

Debug APK: `app/build/outputs/apk/debug/app-debug.apk`.

## Security model

- The bundled HTML is served with `WebViewAssetLoader` from `https://appassets.androidplatform.net/assets/`.
- File access, content access, cleartext traffic, mixed content, popups, geolocation, and arbitrary URI schemes are disabled.
- External HTTP(S) links leave the WebView and open in the system browser.
- No JavaScript-to-native bridge is registered.
- Android backup is disabled until a reviewed data export/restore design exists.

## Important product status

This is **not yet a production AI service**. The supplied V5 HTML is a frontend artifact. This branch does not claim that AI provider calls, GitHub OAuth, Supabase persistence, secure BYOK, user authentication, or cloud synchronization are operational. See [`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md).

## CI

GitHub Actions runs unit tests, Android lint, and debug APK assembly for pushes to this branch and pull requests to `main`. A successful CI run is required before release; no build result is claimed until the workflow has actually completed.
