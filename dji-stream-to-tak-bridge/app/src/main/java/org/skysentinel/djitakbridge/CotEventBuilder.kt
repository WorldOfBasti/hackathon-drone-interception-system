package org.skysentinel.djitakbridge

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

object CotEventBuilder {
    private val cotTimestamp = ThreadLocal.withInitial {
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }
    }

    fun buildDroneEvent(
        uid: String,
        callsign: String,
        sample: TelemetrySample,
        staleSeconds: Long = 120,
    ): String {
        val now = System.currentTimeMillis()
        val formatter = cotTimestamp.get()!!
        val timestamp = formatter.format(Date(now))
        val stale = formatter.format(Date(now + staleSeconds * 1000))
        val safeUid = xml(uid)
        val safeCallsign = xml(callsign)
        val safeSource = xml(sample.source)
        return """
            <event version="2.0" uid="$safeUid" type="a-f-A-M-F" how="m-g" time="$timestamp" start="$timestamp" stale="$stale"><point lat="${sample.latitude}" lon="${sample.longitude}" hae="${sample.altitudeMeters}" ce="5.0" le="5.0"/><detail><contact callsign="$safeCallsign"/><takv device="DJI Mavic Air 2" platform="Android" os="DJI TAK Bridge" version="0.1.0"/><precisionlocation geopointsrc="$safeSource" altsrc="$safeSource"/><track course="${sample.courseDegrees}" speed="${sample.speedMetersPerSecond}"/><remarks>DJI TAK Bridge telemetry</remarks></detail></event>
        """.trimIndent()
    }

    fun uidFromCallsign(callsign: String): String {
        val suffix = callsign.lowercase(Locale.US)
            .replace(Regex("[^a-z0-9]+"), "-")
            .trim('-')
            .ifBlank { "mavic-air-2" }
        return "DJI-MAVIC-AIR2-$suffix"
    }

    private fun xml(value: String): String = buildString(value.length) {
        value.forEach { char ->
            when (char) {
                '&' -> append("&amp;")
                '<' -> append("&lt;")
                '>' -> append("&gt;")
                '"' -> append("&quot;")
                '\'' -> append("&apos;")
                else -> append(char)
            }
        }
    }
}
