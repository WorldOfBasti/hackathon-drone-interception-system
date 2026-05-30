package org.skysentinel.djitakbridge

import dji.common.flightcontroller.FlightControllerState
import dji.sdk.products.Aircraft
import dji.sdk.flightcontroller.FlightController
import kotlin.math.atan2
import kotlin.math.sqrt

class DjiTelemetrySource(
    private val controller: DjiSdkController,
    private val onStatus: (String) -> Unit,
) : TelemetrySource {
    private var flightController: FlightController? = null
    private var lastSentAtMs = 0L

    override fun start(onSample: (TelemetrySample) -> Unit) {
        val aircraft = controller.product as? Aircraft
            ?: throw IllegalStateException("No DJI aircraft connected")
        val nextFlightController = aircraft.flightController
            ?: throw IllegalStateException("DJI flight controller unavailable")

        flightController = nextFlightController
        nextFlightController.setStateCallback(FlightControllerState.Callback { state ->
            val now = System.currentTimeMillis()
            if (now - lastSentAtMs < 1000L) {
                return@Callback
            }
            lastSentAtMs = now

            val location = state.aircraftLocation
            val speed = sqrt(
                state.velocityX.toDouble() * state.velocityX.toDouble() +
                    state.velocityY.toDouble() * state.velocityY.toDouble()
            )
            val course = (Math.toDegrees(
                atan2(state.velocityX.toDouble(), state.velocityY.toDouble())
            ) + 360.0) % 360.0

            val sample = TelemetrySample(
                latitude = location.latitude,
                longitude = location.longitude,
                altitudeMeters = location.altitude.toDouble(),
                courseDegrees = course,
                speedMetersPerSecond = speed,
                source = "dji-sdk",
            )
            if (sample.isValid) {
                onSample(sample)
            } else {
                onStatus("Ignoring invalid DJI GPS point ${sample.latitude}, ${sample.longitude}")
            }
        })
        onStatus("DJI telemetry callback active")
    }

    override fun stop() {
        flightController?.setStateCallback(null)
        flightController = null
    }
}
