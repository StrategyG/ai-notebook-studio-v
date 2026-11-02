package com.dragnodoom.ainotebookstudio

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.net.http.SslError
import android.os.Bundle
import android.webkit.SslErrorHandler
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebResourceResponse
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.webkit.WebViewAssetLoader

/** Secure, offline-first WebView shell. No JavaScript-to-native bridge is exposed. */
class MainActivity : AppCompatActivity() {
    private lateinit var webView: WebView
    private lateinit var assetLoader: WebViewAssetLoader

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        webView = findViewById(R.id.webview)
        configureWebView(webView)
        findViewById<Button>(R.id.docs_button).setOnClickListener {
            startActivity(Intent(this, DocsActivity::class.java))
        }

        if (savedInstanceState == null) {
            webView.loadUrl(APP_URL)
        } else if (webView.restoreState(savedInstanceState) == null) {
            webView.loadUrl(APP_URL)
        }
    }

    private fun configureWebView(view: WebView) {
        SecureWebViewPolicy.configure(view)
        view.isSaveEnabled = true
        view.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                val url = request.url
                val local = assetLoader.shouldInterceptRequest(url)
                if (local != null) return SecureWebViewPolicy.secureAssetResponse(local)
                // Block every non-bundled request, including unexpected main-frame redirects.
                return SecureWebViewPolicy.blockedResponse()
            }

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val uri = request.url
                if (isTrustedAppUrl(uri)) return false
                if (uri.scheme == "https" || uri.scheme == "http") openExternal(uri)
                // Block file:, content:, javascript:, intent:, and unknown schemes.
                return true
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                super.onReceivedError(view, request, error)
                if (request.isForMainFrame) {
                    Toast.makeText(this@MainActivity, R.string.page_load_error, Toast.LENGTH_LONG).show()
                }
            }

            override fun onReceivedSslError(view: WebView?, handler: SslErrorHandler?, error: SslError?) {
                handler?.cancel() // Never bypass certificate errors.
            }
        }
    }

    private fun isTrustedAppUrl(uri: Uri): Boolean =
        AppNavigationPolicy.isLocalAsset(uri.scheme, uri.host, uri.path, uri.port, uri.userInfo)

    private fun openExternal(uri: Uri) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, uri).apply {
                addCategory(Intent.CATEGORY_BROWSABLE)
            })
        } catch (_: ActivityNotFoundException) {
            Toast.makeText(this, R.string.no_browser_found, Toast.LENGTH_SHORT).show()
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        webView.saveState(outState)
        super.onSaveInstanceState(outState)
    }

    @Deprecated("Deprecated in Android API; retained for minSdk compatibility")
    override fun onBackPressed() {
        if (::webView.isInitialized && webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        if (::webView.isInitialized) {
            webView.stopLoading()
            webView.webChromeClient = null
            webView.removeAllViews()
            webView.destroy()
        }
        super.onDestroy()
    }

    companion object {
        private const val APP_URL = "https://appassets.androidplatform.net/assets/index.html"
    }
}
