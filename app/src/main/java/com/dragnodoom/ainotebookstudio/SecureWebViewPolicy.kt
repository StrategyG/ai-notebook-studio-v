package com.dragnodoom.ainotebookstudio

import android.os.Build
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.CookieManager
import java.io.ByteArrayInputStream

/**
 * Central WebView policy for the bundled, offline-first React frontend.
 *
 * The CSP intentionally denies network access. A future AI/backend integration must
 * be reviewed and allow-listed explicitly instead of widening this policy globally.
 */
internal object SecureWebViewPolicy {
    private const val CONTENT_SECURITY_POLICY =
        "default-src 'none'; " +
        "script-src 'self' 'unsafe-inline'; " +
        "style-src 'self' 'unsafe-inline'; " +
        "img-src 'self' data: blob:; " +
        "font-src 'self' data:; " +
        "connect-src 'none'; " +
        "object-src 'none'; " +
        "base-uri 'none'; " +
        "form-action 'none'; " +
        "frame-src 'none'; " +
        "frame-ancestors 'none'; " +
        "worker-src 'none';"

    fun configure(webView: WebView) {
        webView.settings.apply {
            javaScriptEnabled = true // Required by the bundled React UI.
            domStorageEnabled = false // The supplied UI does not use browser storage.
            allowFileAccess = false
            allowContentAccess = false
            allowFileAccessFromFileURLs = false
            allowUniversalAccessFromFileURLs = false
            javaScriptCanOpenWindowsAutomatically = false
            setSupportMultipleWindows(false)
            mediaPlaybackRequiresUserGesture = true
            mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
            cacheMode = android.webkit.WebSettings.LOAD_DEFAULT
            databaseEnabled = false
            setGeolocationEnabled(false)
            builtInZoomControls = false
            displayZoomControls = false
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                safeBrowsingEnabled = true
            }
        }
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false)
    }

    fun secureAssetResponse(response: WebResourceResponse): WebResourceResponse {
        val headers = HashMap(response.responseHeaders ?: emptyMap())
        headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        headers["X-Content-Type-Options"] = "nosniff"
        headers["Referrer-Policy"] = "no-referrer"
        headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        return WebResourceResponse(
            response.mimeType,
            response.encoding,
            response.statusCode,
            response.reasonPhrase,
            headers,
            response.data
        )
    }

    fun blockedResponse(): WebResourceResponse = WebResourceResponse(
        "text/plain",
        "UTF-8",
        403,
        "Blocked by app network policy",
        mapOf("X-Content-Type-Options" to "nosniff"),
        ByteArrayInputStream(ByteArray(0))
    )
}
