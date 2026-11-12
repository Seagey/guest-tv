package app.guesttv.home

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetAddress
import java.net.ServerSocket
import kotlin.concurrent.thread

/** The search with no TV: run by `./gradlew testReleaseUnitTest` (tools/android_test.py runs it). */
class FinderTest {

    @Test fun typedAddresses() {
        assertEquals("http://192.0.2.10:5410", Finder.normalise("192.0.2.10", 5410))
        assertEquals("http://192.0.2.10:5499", Finder.normalise(" 192.0.2.10:5499 ", 5410))
        assertEquals("http://my-computer.local:5410", Finder.normalise("http://My-Computer.local:5410/tv/?home=guest", 5410))
        assertEquals("https://guest.example:443", Finder.normalise("https://guest.example:443", 5410))
        assertNull(Finder.normalise("", 5410))
        assertNull(Finder.normalise("192.0.2", 5410))
        assertNull(Finder.normalise("192.0.2.300", 5410))
        assertNull(Finder.normalise("192.0.2.10:99999", 5410))
        assertNull(Finder.normalise("bad host!", 5410))
        assertNull(Finder.normalise("a..b", 5410))
    }

    @Test fun healthAnswers() {
        assertTrue(Finder.isGuestTv("{\"ok\": true, \"app\": \"guest-tv\"}"))
        assertTrue(Finder.isGuestTv("{\"app\":\"guest-tv\",\"ok\":true}"))
        assertFalse(Finder.isGuestTv("{\"ok\": true}"))                      // couch-tv's bridge, say
        assertFalse(Finder.isGuestTv("{\"ok\": true, \"app\": \"couch-tv\"}"))
        assertFalse(Finder.isGuestTv(null))
    }

    @Test fun subnet() {
        val hosts = Finder.subnetHosts("192.0.2.40")
        assertEquals(253, hosts.size)
        assertFalse("192.0.2.40" in hosts)
        assertTrue("192.0.2.1" in hosts && "192.0.2.254" in hosts)
        assertFalse("192.0.2.0" in hosts || "192.0.2.255" in hosts)
        assertEquals("192.0.2.39", hosts[0])   // nearest first
        assertTrue(Finder.subnetHosts("not an address").isEmpty())
    }

    /** A whole /24 where one address answers late and the rest never do: found, and well inside the budget. */
    @Test fun scanFindsTheOneThatAnswers() {
        val hosts = Finder.subnetHosts("192.0.2.40")
        val start = System.currentTimeMillis()
        val got = Finder.scan(hosts, 5410, budgetMs = 6000) { base ->
            if (base == "http://192.0.2.200:5410") { Thread.sleep(300); true } else { Thread.sleep(700); false }
        }
        assertEquals("http://192.0.2.200:5410", got)
        assertTrue("took ${System.currentTimeMillis() - start} ms", System.currentTimeMillis() - start < 4000)
    }

    @Test fun scanGivesUpInTime() {
        val start = System.currentTimeMillis()
        val got = Finder.scan(Finder.subnetHosts("192.0.2.40"), 5410, budgetMs = 1500) { Thread.sleep(5000); false }
        assertNull(got)
        assertTrue(System.currentTimeMillis() - start < 2500)
    }

    /** The real probe against small web servers on this computer: guest-tv is found, a look-alike is not. */
    @Test fun probeRealServers() {
        /** A tiny web server on this computer that answers every request with [body]. */
        fun serve(body: String): ServerSocket {
            val ss = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"))
            thread(isDaemon = true) {
                while (!ss.isClosed) {
                    val s = runCatching { ss.accept() }.getOrNull() ?: break
                    s.use {
                        val r = it.getInputStream().bufferedReader()
                        while (r.readLine()?.isNotEmpty() == true) Unit   // the request and its headers
                        val b = body.toByteArray()
                        it.getOutputStream().write(("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n" +
                            "Content-Length: ${b.size}\r\nConnection: close\r\n\r\n").toByteArray() + b)
                    }
                }
            }
            return ss
        }
        val guest = serve("{\"ok\": true, \"app\": \"guest-tv\"}")
        val other = serve("{\"ok\": true}")
        try {
            assertTrue(Finder.probe("http://127.0.0.1:${guest.localPort}"))
            assertFalse(Finder.probe("http://127.0.0.1:${other.localPort}"))
            assertFalse(Finder.probe("http://127.0.0.1:1"))   // nothing listening
            assertEquals("http://127.0.0.1:${guest.localPort}", Finder.scan(listOf("127.0.0.1"), guest.localPort))
            assertNull(Finder.scan(listOf("127.0.0.1"), other.localPort))
        } finally {
            guest.close(); other.close()
        }
    }
}
