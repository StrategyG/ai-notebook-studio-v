package com.dragnodoom.ainotebookstudio

import android.content.ActivityNotFoundException
import android.content.Intent
import android.os.Bundle
import android.webkit.WebResourceRequest
import android.net.http.SslError
import android.webkit.SslErrorHandler
import android.webkit.WebView
import android.webkit.WebResourceResponse
import android.webkit.WebViewClient
import android.widget.Toast
import android.widget.TextView
import android.widget.LinearLayout
import android.view.ViewGroup
import androidx.appcompat.app.AppCompatActivity
import androidx.webkit.WebViewAssetLoader

/** Read-only local documentation portal; intentionally exposes no native bridge. */
class DocsActivity : AppCompatActivity() {
    private lateinit var webView: WebView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        webView = WebView(this)
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val demoBanner = TextView(this).apply {
            text = getString(R.string.demo_mode_notice)
            setTextColor(android.graphics.Color.WHITE)
            textSize = 11f
            setPadding(20, 12, 20, 12)
            gravity = android.view.Gravity.CENTER
            setBackgroundColor(android.graphics.Color.rgb(124, 45, 18))
        }
        root.addView(demoBanner, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ))
        root.addView(webView, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f
        ))
        setContentView(root)
        val loader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()
        SecureWebViewPolicy.configure(webView)
        webView.webViewClient = object : WebViewClient() {
            override fun onReceivedSslError(view: WebView?, handler: SslErrorHandler?, error: SslError?) {
                handler?.cancel()
            }
            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: android.webkit.WebResourceError) {
                super.onReceivedError(view, request, error)
                if (request.isForMainFrame) {
                    Toast.makeText(this@DocsActivity, R.string.page_load_error, Toast.LENGTH_LONG).show()
                }
            }
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                val local = loader.shouldInterceptRequest(request.url)
                if (local != null) return SecureWebViewPolicy.secureAssetResponse(local)
                return SecureWebViewPolicy.blockedResponse()
            }
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val uri = request.url
                if (AppNavigationPolicy.isLocalAsset(uri.scheme, uri.host, uri.path, uri.port, uri.userInfo)) return false
                if (uri.scheme == "https" || uri.scheme == "http") {
                    try {
                        startActivity(Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE))
                    } catch (_: ActivityNotFoundException) {
                        Toast.makeText(this@DocsActivity, R.string.no_browser_found, Toast.LENGTH_SHORT).show()
                    }
                }
                return true
            }
        }
        if (savedInstanceState == null) webView.loadUrl("https://appassets.androidplatform.net/assets/docs.html")
        else if (webView.restoreState(savedInstanceState) == null) {
            webView.loadUrl("https://appassets.androidplatform.net/assets/docs.html")
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        webView.saveState(outState)
        super.onSaveInstanceState(outState)
    }

    @Deprecated("Deprecated in Android API; retained for minSdk compatibility")
    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        webView.stopLoading()
        webView.removeAllViews()
        webView.destroy()
        super.onDestroy()
    }
}
