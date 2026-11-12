package app.guesttv.home

import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.URL
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.ThreadFactory
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

/**
 * Finding the guest-tv computer on the Wi-Fi with no typing. Plain Java networking only, no Android
 * classes, so the unit tests run it on the computer (app/src/test).
 *
 * guest-tv answers `GET /api/health` with {"ok": true, "app": "guest-tv"}. The search asks every
 * address in the TV's own /24 (192.0.2.1 to 192.0.2.254 for a TV at 192.0.2.40) at once, with short
 * timeouts, and takes the first one that says it is guest-tv. A couch-tv bridge or any other web
 * server on the same port is not guest-tv and is passed over.
 */
object Finder {
    const val CONNECT_MS = 700
    const val READ_MS = 1200
    const val THREADS = 64
    const val BUDGET_MS = 6_000L

    private val HOST = Regex("[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?")
    private val GUEST_TV = Regex("\"app\"\\s*:\\s*\"guest-tv\"")

    /**
     * What the owner typed (or a computer passed), as a base address: "192.0.2.10",
     * "192.0.2.10:5410", "http://my-computer.local:5410/tv/" all work. Null when it is not an address.
     */
    fun normalise(input: String?, port: Int): String? {
        var s = input?.trim()?.lowercase() ?: return null
        var scheme = "http"
        when {
            s.startsWith("http://") -> s = s.removePrefix("http://")
            s.startsWith("https://") -> { s = s.removePrefix("https://"); scheme = "https" }
        }
        s = s.substringBefore('/').substringBefore('?').substringBefore('#')
        if (s.isEmpty()) return null
        val host: String
        var p = port
        val colon = s.lastIndexOf(':')
        if (colon >= 0) {
            host = s.substring(0, colon)
            p = s.substring(colon + 1).toIntOrNull()?.takeIf { it in 1..65535 } ?: return null
        } else host = s
        if (!HOST.matches(host) || host.contains("..")) return null
        // A number address must be four numbers of 0 to 255.
        if (host.all { it.isDigit() || it == '.' }) {
            val parts = host.split('.')
            if (parts.size != 4 || parts.any { it.isEmpty() || it.length > 3 || it.toInt() > 255 }) return null
        }
        return "$scheme://$host:$p"
    }

    /** True when a /api/health answer is guest-tv's. */
    fun isGuestTv(body: String?): Boolean = body != null && GUEST_TV.containsMatchIn(body)

    /** Every other address in the same /24 as [own] ("192.0.2.40" gives .1 to .254 without .40). */
    fun subnetHosts(own: String): List<String> {
        val parts = own.split('.')
        if (parts.size != 4 || parts.any { it.toIntOrNull() == null }) return emptyList()
        val net = parts.take(3).joinToString(".")
        val me = parts[3].toInt()
        // Nearest first: home routers hand out addresses close together, so the computer is often
        // next to the TV. All of them are asked at once anyway; this only orders the queue.
        return (1..254).filter { it != me }.sortedBy { kotlin.math.abs(it - me) }.map { "$net.$it" }
    }

    /** This device's own IPv4 addresses on a local network (Wi-Fi or Ethernet), never loopback. */
    fun ownAddresses(): List<String> = runCatching {
        NetworkInterface.getNetworkInterfaces().toList()
            .filter { runCatching { it.isUp && !it.isLoopback }.getOrDefault(false) }
            .flatMap { it.inetAddresses.toList() }
            .filterIsInstance<Inet4Address>()
            .filter { it.isSiteLocalAddress }
            .mapNotNull { it.hostAddress }
            .distinct()
    }.getOrDefault(emptyList())

    /** Asks one address whether it is guest-tv. */
    fun probe(base: String, connectMs: Int = CONNECT_MS, readMs: Int = READ_MS): Boolean = try {
        val c = URL("$base/api/health").openConnection() as HttpURLConnection
        c.connectTimeout = connectMs
        c.readTimeout = readMs
        c.instanceFollowRedirects = false
        try {
            if (c.responseCode !in 200..299) false
            else isGuestTv(c.inputStream.use { readSome(it, 4096) })
        } finally { c.disconnect() }
    } catch (e: Exception) {
        false
    }

    /** The first [max] bytes of an answer as text (InputStream.readNBytes is Android 13 and newer only). */
    private fun readSome(s: java.io.InputStream, max: Int): String {
        val buf = ByteArray(max)
        var got = 0
        while (got < max) {
            val r = s.read(buf, got, max - got)
            if (r < 0) break
            got += r
        }
        return String(buf, 0, got, Charsets.UTF_8)
    }

    /**
     * Asks every host at once (up to [threads] at a time) and returns the first base address that is
     * guest-tv, or null when none answered within [budgetMs].
     */
    fun scan(
        hosts: List<String>,
        port: Int,
        budgetMs: Long = BUDGET_MS,
        threads: Int = THREADS,
        probe: (String) -> Boolean = { Finder.probe(it) },
    ): String? {
        if (hosts.isEmpty()) return null
        val found = AtomicReference<String?>(null)
        val done = CountDownLatch(1)
        val left = AtomicInteger(hosts.size)
        val n = AtomicInteger()
        val pool = Executors.newFixedThreadPool(minOf(threads, hosts.size), ThreadFactory { r ->
            Thread(r, "guesttv-scan-" + n.incrementAndGet()).apply { isDaemon = true }
        })
        try {
            for (h in hosts) pool.execute {
                try {
                    if (found.get() == null) {
                        val base = "http://$h:$port"
                        if (probe(base) && found.compareAndSet(null, base)) done.countDown()
                    }
                } finally {
                    if (left.decrementAndGet() == 0) done.countDown()
                }
            }
            done.await(budgetMs, TimeUnit.MILLISECONDS)
            return found.get()
        } finally {
            pool.shutdownNow()
        }
    }

    /** The whole search: the TV's own /24 on each of its networks. */
    fun search(port: Int, budgetMs: Long = BUDGET_MS): String? {
        val hosts = ownAddresses().flatMap { subnetHosts(it) }.distinct()
        return scan(hosts, port, budgetMs)
    }
}
