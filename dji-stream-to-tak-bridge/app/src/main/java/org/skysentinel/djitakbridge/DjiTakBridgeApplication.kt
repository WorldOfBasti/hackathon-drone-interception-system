package org.skysentinel.djitakbridge

import android.app.Application
import android.content.Context
import android.content.pm.PackageManager
import android.util.Log

class DjiTakBridgeApplication : Application() {
    override fun attachBaseContext(base: Context) {
        super.attachBaseContext(base)
        if (shouldRunNativeBootstrap(base)) {
            runDjiNativeBootstrap()
        }
    }

    @Suppress("DEPRECATION")
    private fun shouldRunNativeBootstrap(context: Context): Boolean {
        return try {
            val appInfo = context.packageManager.getApplicationInfo(
                context.packageName,
                PackageManager.GET_META_DATA,
            )
            val appKey = appInfo.metaData?.getString("com.dji.sdk.API_KEY").orEmpty()
            val enabled = when (
                val value = appInfo.metaData?.get("org.skysentinel.djitakbridge.DJI_ENABLE_NATIVE_BOOTSTRAP")
            ) {
                is Boolean -> value
                is String -> value.toBoolean()
                else -> false
            }
            enabled && appKey.isNotBlank() && appKey != "PASTE_DJI_APP_KEY_HERE"
        } catch (_: Exception) {
            false
        }
    }

    private fun runDjiNativeBootstrap() {
        try {
            Log.i(TAG, "DJI native bootstrap enabled")
            val helper = Class.forName("com.cySdkyc.clx.Helper")
            helper.getMethod("install", Application::class.java).invoke(null, this)
            Log.i(TAG, "DJI native bootstrap completed")
        } catch (error: Throwable) {
            Log.e(TAG, "DJI native bootstrap failed: ${error.message ?: error.javaClass.simpleName}", error)
            // Let the app continue in simulator/manual mode if DJI's legacy native bootstrap fails.
        }
    }

    private companion object {
        const val TAG = "DjiTakBridge"
    }
}
