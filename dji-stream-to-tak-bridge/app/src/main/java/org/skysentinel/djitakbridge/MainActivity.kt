package org.skysentinel.djitakbridge

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.text.InputType
import android.util.Log
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.util.Locale
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private lateinit var hostField: EditText
    private lateinit var portField: EditText
    private lateinit var callsignField: EditText
    private lateinit var simulatorCheck: CheckBox
    private lateinit var streamButton: Button
    private lateinit var djiStatusView: TextView
    private lateinit var takStatusView: TextView
    private lateinit var lastSampleView: TextView

    private lateinit var djiController: DjiSdkController
    private val takClient = TakTcpClient(::setTakStatus)
    private val sendExecutor: ExecutorService = Executors.newSingleThreadExecutor()
    private var telemetrySource: TelemetrySource? = null
    private var streaming = false
    private var activeHost = DEFAULT_TAK_HOST
    private var activePort = 8088
    private var activeCallsign = "Mavic Air 2"
    private var activeUid = CotEventBuilder.uidFromCallsign(activeCallsign)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildUi()
        applyIntentOverrides()
        djiController = DjiSdkController(this, ::setDjiStatus, ::onDjiProductReady)
        requestRuntimePermissions()
        setDjiStatus("Ready")
        if (intent.getBooleanExtra("autoStart", false)) {
            streamButton.post { startStreaming() }
        }
    }

    override fun onDestroy() {
        stopStreaming()
        sendExecutor.shutdownNow()
        takClient.close()
        super.onDestroy()
    }

    private fun buildUi() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(24), dp(20), dp(24))
        }

        root.addView(TextView(this).apply {
            text = "DJI TAK Bridge"
            textSize = 26f
            typeface = Typeface.DEFAULT_BOLD
        })
        root.addView(TextView(this).apply {
            text = "Streams DJI Mavic Air 2 coordinates as CoT to OpenTAKServer."
            textSize = 14f
            setPadding(0, dp(4), 0, dp(18))
        })

        hostField = editText("TAK host", DEFAULT_TAK_HOST, InputType.TYPE_CLASS_TEXT)
        portField = editText("TAK TCP port", "8088", InputType.TYPE_CLASS_NUMBER)
        callsignField = editText("Drone callsign", "Mavic Air 2", InputType.TYPE_CLASS_TEXT)
        simulatorCheck = CheckBox(this).apply {
            text = "Use simulated telemetry"
            isChecked = false
            setPadding(0, dp(8), 0, dp(8))
        }
        streamButton = Button(this).apply {
            text = "Start Stream"
            setOnClickListener { toggleStreaming() }
        }
        djiStatusView = statusText("DJI: starting")
        takStatusView = statusText("TAK: idle")
        lastSampleView = statusText("Last point: none")

        root.addView(label("Connection"))
        root.addView(hostField)
        root.addView(portField)
        root.addView(callsignField)
        root.addView(simulatorCheck)
        root.addView(streamButton)
        root.addView(label("Status"))
        root.addView(djiStatusView)
        root.addView(takStatusView)
        root.addView(lastSampleView)

        setContentView(ScrollView(this).apply { addView(root) })
    }

    private fun toggleStreaming() {
        if (streaming) {
            stopStreaming()
        } else {
            startStreaming()
        }
    }

    private fun startStreaming() {
        activeHost = hostField.text.toString().trim().ifBlank { DEFAULT_TAK_HOST }
        activePort = portField.text.toString().trim().toIntOrNull() ?: 8088
        activeCallsign = callsignField.text.toString().trim().ifBlank { "Mavic Air 2" }
        activeUid = CotEventBuilder.uidFromCallsign(activeCallsign)

        if (simulatorCheck.isChecked) {
            if (!startTelemetrySource(SimulatedTelemetrySource())) {
                return
            }
            setTakStatus("TAK: streaming to $activeHost:$activePort")
        } else {
            if (!djiController.registerIfConfigured()) {
                return
            }
            setDjiStatus("Waiting for DJI aircraft/controller")
            setTakStatus("TAK: waiting for real DJI telemetry to $activeHost:$activePort")
        }

        streaming = true
        streamButton.text = "Stop Stream"
        simulatorCheck.isEnabled = false
        if (!simulatorCheck.isChecked) {
            startDjiTelemetryIfReady()
        }
    }

    private fun startTelemetrySource(source: TelemetrySource): Boolean {
        return try {
            source.start { sample ->
                if (!sample.isValid) {
                    setTakStatus("TAK: skipped invalid point")
                    return@start
                }
                val cot = CotEventBuilder.buildDroneEvent(activeUid, activeCallsign, sample)
                sendExecutor.execute {
                    try {
                        takClient.send(activeHost, activePort, cot)
                        setTakStatus("TAK: sent ${sample.source} CoT")
                        setLastSample(sample)
                    } catch (error: Exception) {
                        setTakStatus("TAK send failed: ${error.message ?: error.javaClass.simpleName}")
                    }
                }
            }
            telemetrySource = source
            true
        } catch (error: Throwable) {
            setDjiStatus(error.message ?: error.javaClass.simpleName)
            false
        }
    }

    private fun onDjiProductReady() = runOnUiThread {
        if (streaming && !simulatorCheck.isChecked && telemetrySource == null) {
            startDjiTelemetryIfReady()
        }
    }

    private fun startDjiTelemetryIfReady() {
        if (telemetrySource != null) {
            return
        }
        if (djiController.product == null) {
            setDjiStatus("Waiting for DJI aircraft/controller")
            return
        }
        if (startTelemetrySource(DjiTelemetrySource(djiController, ::setDjiStatus))) {
            setTakStatus("TAK: streaming real DJI telemetry to $activeHost:$activePort")
        }
    }

    private fun stopStreaming() {
        telemetrySource?.stop()
        telemetrySource = null
        takClient.close()
        streaming = false
        activeHost = hostField.text.toString().trim().ifBlank { DEFAULT_TAK_HOST }
        activePort = portField.text.toString().trim().toIntOrNull() ?: 8088
        activeCallsign = callsignField.text.toString().trim().ifBlank { "Mavic Air 2" }
        activeUid = CotEventBuilder.uidFromCallsign(activeCallsign)
        if (::streamButton.isInitialized) {
            streamButton.text = "Start Stream"
            simulatorCheck.isEnabled = true
            setTakStatus("TAK: stopped")
        }
    }

    private fun requestRuntimePermissions() {
        val permissions = mutableListOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION,
            Manifest.permission.READ_PHONE_STATE,
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            permissions += Manifest.permission.BLUETOOTH_CONNECT
        }
        val missing = permissions.filter {
            checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isNotEmpty()) {
            requestPermissions(missing.toTypedArray(), 42)
        }
    }

    private fun applyIntentOverrides() {
        intent.getStringExtra("takHost")?.takeIf { it.isNotBlank() }?.let {
            hostField.setText(it)
        }
        val takPort = intent.getIntExtra("takPort", -1)
        if (takPort > 0) {
            portField.setText(takPort.toString())
        }
        intent.getStringExtra("callsign")?.takeIf { it.isNotBlank() }?.let {
            callsignField.setText(it)
        }
        if (intent.hasExtra("simulator")) {
            simulatorCheck.isChecked = intent.getBooleanExtra("simulator", true)
        }
    }

    private fun setDjiStatus(message: String) = runOnUiThread {
        val status = if (message.startsWith("DJI:")) message else "DJI: $message"
        Log.i(TAG, status)
        djiStatusView.text = status
    }

    private fun setTakStatus(message: String) = runOnUiThread {
        Log.i(TAG, message)
        takStatusView.text = message
    }

    private fun setLastSample(sample: TelemetrySample) = runOnUiThread {
        lastSampleView.text = String.format(
            Locale.US,
            "Last point: %.6f, %.6f  %.1fm  %.1fm/s",
            sample.latitude,
            sample.longitude,
            sample.altitudeMeters,
            sample.speedMetersPerSecond,
        )
    }

    private fun label(text: String): TextView = TextView(this).apply {
        this.text = text
        textSize = 16f
        typeface = Typeface.DEFAULT_BOLD
        setPadding(0, dp(18), 0, dp(6))
    }

    private fun statusText(text: String): TextView = TextView(this).apply {
        this.text = text
        textSize = 14f
        setPadding(0, dp(4), 0, dp(4))
    }

    private fun editText(hint: String, value: String, inputTypeValue: Int): EditText =
        EditText(this).apply {
            this.hint = hint
            setText(value)
            inputType = inputTypeValue
            isSingleLine = true
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO
        }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private companion object {
        const val TAG = "DjiTakBridge"
        const val DEFAULT_TAK_HOST = "192.0.2.10"
    }
}
