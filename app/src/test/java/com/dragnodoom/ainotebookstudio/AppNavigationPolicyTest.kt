package com.dragnodoom.ainotebookstudio

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AppNavigationPolicyTest {
    @Test
    fun allowsOnlyBundledHttpsEntryPoints() {
        assertTrue(AppNavigationPolicy.isLocalAsset(
            "https", "appassets.androidplatform.net", "/assets/index.html"
        ))
        assertTrue(AppNavigationPolicy.isLocalAsset(
            "https", "APPASSETS.ANDROIDPLATFORM.NET", "/assets/docs.html"
        ))
    }

    @Test
    fun rejectsHttpAndUntrustedHosts() {
        assertFalse(AppNavigationPolicy.isLocalAsset(
            "http", "appassets.androidplatform.net", "/assets/index.html"
        ))
        assertFalse(AppNavigationPolicy.isLocalAsset(
            "https", "evil.example", "/assets/index.html"
        ))
        assertFalse(AppNavigationPolicy.isLocalAsset(
            "https", "appassets.androidplatform.net.evil.example", "/assets/index.html"
        ))
    }

    @Test
    fun rejectsUnknownPathsAndTraversal() {
        assertFalse(AppNavigationPolicy.isLocalAsset(
            "https", "appassets.androidplatform.net", "/assets/private.html"
        ))
        assertFalse(AppNavigationPolicy.isLocalAsset(
            "https", "appassets.androidplatform.net", "/assets/../private"
        ))
        assertFalse(AppNavigationPolicy.isLocalAsset(
            "https", "appassets.androidplatform.net", null
        ))
    }

    @Test
    fun rejectsExplicitPortsAndUserInfo() {
        assertFalse(AppNavigationPolicy.isLocalAsset(
            "https", "appassets.androidplatform.net", "/assets/index.html", 443
        ))
        assertFalse(AppNavigationPolicy.isLocalAsset(
            "https", "appassets.androidplatform.net", "/assets/index.html", -1, "attacker"
        ))
    }
}
