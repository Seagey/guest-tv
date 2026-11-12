package app.guesttv.home

import android.accessibilityservice.AccessibilityService
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import android.util.Log
import android.view.accessibility.AccessibilityEvent

/**
 * The Home button watch (from couch-tv's app). Some TVs keep sending the Home button, and the TV
 * at power on, to their own home: Fire TV always (Amazon's home cannot be replaced), and some
 * Google TVs whose own home outranks the default home setting. This watch sees the TV's own home
 * come on screen and puts Guest TV back on top. The TV's home flashes up for a moment; without root
 * that is as good as Android allows.
 *
 * Opt in, twice over: the switch in Guest TV's own settings ([wanted]), and Android's switch for
 * the service in the TV's Settings, Accessibility, which only the owner can turn on with the remote.
 * With the first off the service does nothing even when Android has it switched on. It only sees
 * which window came forward and reads no screen content. If Guest TV keeps crashing (CrashGuard),
 * the watch stands aside and leaves the TV's own home on screen.
 */
class FireWatch : AccessibilityService() {
    private var last = 0L
    private val handler = Handler(Looper.getMainLooper())
    private var stockInFront = false
    private var recheckPending = false
    private val recheck = Runnable {
        recheckPending = false
        if (stockInFront && active()) bringBack()
    }

    private fun active() = wanted(this) && !CrashGuard.standingAside(this)

    override fun onInterrupt() {}

    override fun onServiceConnected() {
        connected = true
        homeClasses = homeActivitiesOf(this)
        Log.i("guesttv.watch", "the Home button watch is connected")
        // Fire TV and TCL open their own home at power on before this service is bound, so that
        // window event is never seen: bound in the first minutes after a restart, nothing but the
        // TV's own home can be in front, so Guest TV goes on top once. Other TVs are left alone (one
        // can start on an HDMI input, and that must never be covered).
        if ((Build.MANUFACTURER.equals("Amazon", ignoreCase = true) || TclPlaceholderInput.isTcl()) &&
            SystemClock.elapsedRealtime() < BOOT_WINDOW_MS && active()) {
            runCatching { startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
        }
    }

    override fun onUnbind(intent: Intent?): Boolean {
        connected = false
        handler.removeCallbacks(recheck)
        recheckPending = false
        return super.onUnbind(intent)
    }

    override fun onAccessibilityEvent(e: AccessibilityEvent) {
        if (e.eventType != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) return
        stockInFront = isStockHome(e.packageName?.toString(), e.className?.toString())
        if (!stockInFront || !active()) return
        val wait = DEBOUNCE_MS - (System.currentTimeMillis() - last)
        if (wait > 0) {
            // A repeat press: look once more when the debounce ends, in case the TV's home stayed in front.
            if (!recheckPending) {
                recheckPending = true
                handler.postDelayed(recheck, wait + 50)
            }
            return
        }
        bringBack()
    }

    private fun bringBack() {
        last = System.currentTimeMillis()
        runCatching { startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
    }

    /** After an update or a reboot: put the watch back on, only where the owner chose it. */
    class Restore : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) {
            if (i.action == Intent.ACTION_MY_PACKAGE_REPLACED) CrashGuard.reset(c)
            runCatching { ensure(c) }
        }
    }

    companion object {
        @Volatile var connected = false
        private const val DEBOUNCE_MS = 1200L
        private const val BOOT_WINDOW_MS = 2 * 60_000L
        private const val PREFS = "guest"
        private const val KEY = "watch"

        const val AMAZON_HOME = "com.amazon.tv.launcher"
        const val GOOGLE_TV_HOME = "com.google.android.apps.tv.launcherx"
        const val ANDROID_TV_HOME = "com.google.android.tvlauncher"
        private val STOCK_HOMES = listOf(AMAZON_HOME, GOOGLE_TV_HOME, ANDROID_TV_HOME)

        /** The owner's switch in Guest TV's settings. Off until they turn it on. */
        fun wanted(c: Context) = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY, false)

        fun setWanted(c: Context, on: Boolean) {
            c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY, on).apply()
            if (on) { TclPlaceholderInput.enableIfTcl(c); ensure(c) } else remove(c)
        }

        /** Android has the service switched on (the owner did it in Settings, Accessibility, or a computer did). */
        fun enabledInSettings(c: Context): Boolean = runCatching {
            val list = Settings.Secure.getString(c.contentResolver, "enabled_accessibility_services") ?: ""
            list.split(':').any { it == me(c) || it == "${c.packageName}/.FireWatch" }
        }.getOrDefault(false)

        private fun me(c: Context) = "${c.packageName}/${FireWatch::class.java.name}"

        private fun canWrite(c: Context) =
            c.checkSelfPermission("android.permission.WRITE_SECURE_SETTINGS") == PackageManager.PERMISSION_GRANTED

        @Volatile var homeClasses: Set<String> = emptySet()

        /** The activities of the Google homes that the TV itself lists as a HOME screen. */
        fun homeActivitiesOf(c: Context): Set<String> = runCatching {
            val q = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
            c.packageManager.queryIntentActivities(q, 0)
                .filter { it.activityInfo.packageName == GOOGLE_TV_HOME || it.activityInfo.packageName == ANDROID_TV_HOME }
                .map { it.activityInfo.name }.toSet()
        }.getOrDefault(emptySet())

        /** The TV's own home screen, not its Settings, profile or setup screens. */
        fun isStockHome(pkg: String?, cls: String?, homes: Set<String> = homeClasses): Boolean = when (pkg) {
            AMAZON_HOME -> cls?.contains("Settings") != true
            GOOGLE_TV_HOME -> cls == "$GOOGLE_TV_HOME.home.HomeActivity" || cls == "$GOOGLE_TV_HOME.home.VanillaModeHomeActivity" || (cls != null && cls in homes)
            ANDROID_TV_HOME -> cls == "$ANDROID_TV_HOME.MainActivity" || (cls != null && cls in homes)
            else -> false
        }

        /**
         * Only where the owner chose the watch AND a computer once granted secure settings over ADB:
         * switch the service back on after Android dropped it (an update does). Without that grant
         * the owner's Accessibility switch is the only way on, which is the no-ADB path.
         */
        fun ensure(c: Context) {
            if (!wanted(c) || !canWrite(c)) return
            if (STOCK_HOMES.none { p -> runCatching { c.packageManager.getPackageInfo(p, 0) }.isSuccess }) return
            runCatching {
                val cr = c.contentResolver
                val list = (Settings.Secure.getString(cr, "enabled_accessibility_services") ?: "").split(':').filter { it.isNotEmpty() && it != "null" }
                if (list.none { it == me(c) || it == "${c.packageName}/.FireWatch" }) {
                    Settings.Secure.putString(cr, "enabled_accessibility_services", (list + me(c)).joinToString(":"))
                }
                Settings.Secure.putInt(cr, "accessibility_enabled", 1)
            }.onFailure { Log.w("guesttv.watch", "could not switch the watch on: ${it.message}") }
        }

        /** Switched off in Guest TV's settings: take it out of Android's list too, where the app is allowed to. */
        private fun remove(c: Context) {
            if (!canWrite(c)) return
            runCatching {
                val cr = c.contentResolver
                val list = (Settings.Secure.getString(cr, "enabled_accessibility_services") ?: "").split(':').filter { it.isNotEmpty() && it != "null" }
                val rest = list.filter { it != me(c) && it != "${c.packageName}/.FireWatch" }
                if (rest.size != list.size) Settings.Secure.putString(cr, "enabled_accessibility_services", rest.joinToString(":"))
            }
        }
    }
}
