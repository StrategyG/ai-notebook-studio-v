package com.dragnodoom.ainotebookstudio

/** Strict, framework-free allow-list for the app's two bundled HTML entry points. */
internal object AppNavigationPolicy {
    private const val ASSET_HOST = "appassets.androidplatform.net"

    fun isLocalAsset(
        scheme: String?,
        host: String?,
        path: String?,
        port: Int = -1,
        userInfo: String? = null
    ): Boolean =
        scheme.equals("https", ignoreCase = true) &&
            host.equals(ASSET_HOST, ignoreCase = true) &&
            port == -1 &&
            userInfo.isNullOrEmpty() &&
            (path == "/assets/index.html" || path == "/assets/docs.html")
}
