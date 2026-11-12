package app.guesttv.home

import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import android.media.tv.TvInputService
import android.os.Build
import android.util.Log

/**
 * A TV input that does nothing, for TCL TVs only (from couch-tv's app, couch-tv#94).
 *
 * TCL's boot manager refuses, on every boot, to bind an app's accessibility service unless the app
 * provides a TV input, so without this the Home button watch is gone after each restart on a TCL.
 * The service is declared switched off in the manifest and [enableIfTcl] switches it on, once, only
 * when the maker or brand is TCL, so no other TV lists a new input.
 */
class TclPlaceholderInput : TvInputService() {
    /** No session: nothing ever plays. */
    override fun onCreateSession(inputId: String): Session? = null

    companion object {
        fun isTcl(): Boolean = Build.MANUFACTURER.equals("TCL", ignoreCase = true) ||
            Build.BRAND.equals("TCL", ignoreCase = true)

        /** Switch the placeholder input on, on a TCL TV only. Safe to call on every start. */
        fun enableIfTcl(c: Context) {
            if (!isTcl()) return
            runCatching {
                val me = ComponentName(c, TclPlaceholderInput::class.java)
                if (c.packageManager.getComponentEnabledSetting(me) != PackageManager.COMPONENT_ENABLED_STATE_ENABLED) {
                    c.packageManager.setComponentEnabledSetting(me, PackageManager.COMPONENT_ENABLED_STATE_ENABLED, PackageManager.DONT_KILL_APP)
                    Log.i("guesttv.tcl", "TCL TV: placeholder TV input switched on")
                }
            }
        }
    }
}
