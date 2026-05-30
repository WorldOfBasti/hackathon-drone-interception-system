package org.skysentinel.djitakbridge

import android.content.Context
import android.content.pm.PackageManager
import dji.common.error.DJIError
import dji.common.error.DJISDKError
import dji.sdk.base.BaseComponent
import dji.sdk.base.BaseProduct
import dji.sdk.sdkmanager.DJISDKInitEvent
import dji.sdk.sdkmanager.DJISDKManager

class DjiSdkController(
    private val context: Context,
    private val onStatus: (String) -> Unit,
    private val onProductReady: () -> Unit,
) {
    @Volatile
    var product: BaseProduct? = null
        private set

    @Volatile
    private var registrationStarted = false

    fun registerIfConfigured(): Boolean {
        val appKey = readDjiAppKey()
        if (appKey.isBlank() || appKey == "PASTE_DJI_APP_KEY_HERE") {
            onStatus("DJI app key missing; simulator mode is ready")
            return false
        }
        if (registrationStarted) {
            onStatus("DJI SDK registration already started")
            return try {
                DJISDKManager.getInstance().startConnectionToProduct()
                true
            } catch (error: Throwable) {
                registrationStarted = false
                onStatus("DJI SDK unavailable: ${error.message ?: error.javaClass.simpleName}")
                false
            }
        }

        registrationStarted = true
        onStatus("Registering DJI SDK")
        try {
            DJISDKManager.getInstance().registerApp(
                context.applicationContext,
                object : DJISDKManager.SDKManagerCallback {
                    override fun onRegister(error: DJIError?) {
                        if (error == DJISDKError.REGISTRATION_SUCCESS) {
                            onStatus("DJI SDK registered; connecting to product")
                            DJISDKManager.getInstance().startConnectionToProduct()
                        } else {
                            onStatus("DJI SDK registration failed: ${error?.description ?: "unknown"}")
                        }
                    }

                    override fun onProductDisconnect() {
                        product = null
                        onStatus("DJI product disconnected")
                    }

                    override fun onProductConnect(baseProduct: BaseProduct?) {
                        product = baseProduct
                        onStatus("DJI product connected: ${baseProduct?.model?.displayName ?: "unknown"}")
                        onProductReady()
                    }

                    override fun onProductChanged(baseProduct: BaseProduct?) {
                        product = baseProduct
                        onStatus("DJI product changed: ${baseProduct?.model?.displayName ?: "unknown"}")
                        onProductReady()
                    }

                    override fun onComponentChange(
                        key: BaseProduct.ComponentKey?,
                        oldComponent: BaseComponent?,
                        newComponent: BaseComponent?,
                    ) {
                        newComponent?.setComponentListener { connected ->
                            onStatus("DJI component ${key?.toString() ?: "unknown"} connected=$connected")
                        }
                    }

                    override fun onInitProcess(event: DJISDKInitEvent?, totalProcess: Int) {
                        onStatus("DJI init ${event?.toString() ?: "event"} $totalProcess%")
                    }

                    override fun onDatabaseDownloadProgress(current: Long, total: Long) {
                        if (total > 0L) {
                            onStatus("DJI fly-safe DB $current/$total")
                        }
                    }
                },
            )
        } catch (error: Throwable) {
            registrationStarted = false
            onStatus("DJI SDK unavailable: ${error.message ?: error.javaClass.simpleName}")
            return false
        }
        return true
    }

    @Suppress("DEPRECATION")
    private fun readDjiAppKey(): String {
        val appInfo = context.packageManager.getApplicationInfo(
            context.packageName,
            PackageManager.GET_META_DATA,
        )
        return appInfo.metaData?.getString("com.dji.sdk.API_KEY").orEmpty()
    }
}
