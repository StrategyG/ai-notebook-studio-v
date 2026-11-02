package com.dragnodoom.ainotebookstudio

import android.os.Bundle
import android.webkit.WebView
import androidx.appcompat.app.AppCompatActivity

class DocsActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val webView = WebView(this)
        setContentView(webView)
        webView.settings.javaScriptEnabled = true
        webView.settings.domStorageEnabled = true
        webView.settings.allowFileAccess = true
        webView.loadUrl("file:///android_asset/docs.html")
    }
}
