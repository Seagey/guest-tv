package app.guesttv.home

import android.app.Application

/** Starts the crash guard before anything else in the app runs (CrashGuard.kt). */
class App : Application() {
    override fun onCreate() {
        super.onCreate()
        CrashGuard.install(this)
        if (FireWatch.wanted(this)) TclPlaceholderInput.enableIfTcl(this)   // TCL only, and only with the watch chosen
    }
}
