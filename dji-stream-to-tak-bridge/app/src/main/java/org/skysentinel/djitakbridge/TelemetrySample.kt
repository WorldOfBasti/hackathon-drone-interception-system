package org.skysentinel.djitakbridge

data class TelemetrySample(
    val latitude: Double,
    val longitude: Double,
    val altitudeMeters: Double,
    val courseDegrees: Double,
    val speedMetersPerSecond: Double,
    val source: String,
) {
    val isValid: Boolean
        get() = latitude in -90.0..90.0 && longitude in -180.0..180.0 &&
            latitude != 0.0 && longitude != 0.0
}

interface TelemetrySource {
    fun start(onSample: (TelemetrySample) -> Unit)
    fun stop()
}
