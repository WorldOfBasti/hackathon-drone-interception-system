package org.skysentinel.djitakbridge

import kotlin.concurrent.thread
import kotlin.math.cos
import kotlin.math.sin

class SimulatedTelemetrySource : TelemetrySource {
    @Volatile
    private var running = false
    private var worker: Thread? = null

    override fun start(onSample: (TelemetrySample) -> Unit) {
        stop()
        running = true
        worker = thread(name = "simulated-drone-telemetry") {
            val baseLat = 48.137
            val baseLon = 11.575
            var tick = 0
            while (running) {
                val angle = tick / 12.0
                val lat = baseLat + sin(angle) * 0.0015
                val lon = baseLon + cos(angle) * 0.0015
                val course = (Math.toDegrees(angle) % 360.0 + 360.0) % 360.0
                onSample(
                    TelemetrySample(
                        latitude = lat,
                        longitude = lon,
                        altitudeMeters = 95.0 + sin(angle / 2.0) * 15.0,
                        courseDegrees = course,
                        speedMetersPerSecond = 8.0,
                        source = "simulator",
                    )
                )
                tick += 1
                Thread.sleep(1000)
            }
        }
    }

    override fun stop() {
        running = false
        worker?.interrupt()
        worker = null
    }
}
