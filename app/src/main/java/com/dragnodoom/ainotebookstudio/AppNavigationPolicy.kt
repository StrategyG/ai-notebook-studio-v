package com.dragnodoom.ainotebookstudio

/** Pure URL policy shared by WebViews; no Android framework dependency. */
internal object AppNavigationPolicy {
    private const val ASSET_HOST = "appassets.androidplatform.net"

    fun isLocalAsset(scheme: String?, host: String?, path: String?): Boolean =
        scheme.equals("https", ignoreCase = true) &&
            host.equals(ASSET_HOST, ignoreCase = true) &&
            path?.startsWith("/assets/") == true
}
