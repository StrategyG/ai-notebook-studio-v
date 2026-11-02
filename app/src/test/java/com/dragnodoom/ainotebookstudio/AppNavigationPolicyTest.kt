package com.dragnodoom.ainotebookstudio

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AppNavigationPolicyTest {
    @Test
    fun allowsOnlyHttpsAssetOrigin() {
        assertTrue(
            AppNavigationPolicy.isLocalAsset(
                "https", "appassets.androidplatform.net", "/assets/index.html"
            )
        )
    }

    @Test
    fun rejectsHttpAndUntrustedHosts() {
        assertFalse(
            AppNavigationPolicy.isLocalAsset(
                "http", "appassets.androidplatform.net", "/assets/index.html"
            )
        )
        assertFalse(
            AppNavigationPolicy.isLocalAsset(
                "https", "evil.example", "/assets/index.html"
            )
        )
    }

    @Test
    fun rejectsPathsOutsideAssetsDirectory() {
        assertFalse(
            AppNavigationPolicy.isLocalAsset(
                "https", "appassets.androidplatform.net", "/private/token"
            )
        )
        assertFalse(
            AppNavigationPolicy.isLocalAsset(
                "https", "appassets.androidplatform.net", null
            )
        )
    }
}
