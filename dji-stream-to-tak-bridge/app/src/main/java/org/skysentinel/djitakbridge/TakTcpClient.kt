package org.skysentinel.djitakbridge

import java.io.Closeable
import java.net.InetSocketAddress
import java.net.Socket
import java.nio.charset.StandardCharsets

class TakTcpClient(
    private val onStatus: (String) -> Unit,
) : Closeable {
    private val lock = Any()
    private var socket: Socket? = null

    fun send(host: String, port: Int, payload: String) {
        synchronized(lock) {
            val activeSocket = socket?.takeIf { it.isConnected && !it.isClosed }
                ?: connect(host, port)
            try {
                activeSocket.getOutputStream().write(payload.toByteArray(StandardCharsets.UTF_8))
                activeSocket.getOutputStream().flush()
            } catch (error: Exception) {
                closeCurrent()
                throw error
            }
        }
    }

    override fun close() {
        synchronized(lock) {
            closeCurrent()
        }
    }

    private fun connect(host: String, port: Int): Socket {
        closeCurrent()
        val next = Socket()
        next.tcpNoDelay = true
        next.connect(InetSocketAddress(host, port), 5000)
        socket = next
        onStatus("TAK connected to $host:$port")
        return next
    }

    private fun closeCurrent() {
        try {
            socket?.close()
        } catch (_: Exception) {
        } finally {
            socket = null
        }
    }
}
