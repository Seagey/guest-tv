package app.guesttv.home

import android.app.Activity
import android.app.role.RoleManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.provider.Settings

/**
 * Making Guest TV the home screen with no computer (from couch-tv's app, couch-tv#98). On Android 10
 * and newer Android has its own "default home app" request: it shows the system's own chooser and
 * the owner picks Guest TV with the remote. Older Androids get the Home settings screen if there is
 * one, else Android's "Select a home app" chooser. It never switches off or removes the TV's own home.
 */
object HomeRole {
    const val REQUEST = 42

    private fun installed(c: Context, pkg: String) = try {
        c.packageManager.getPackageInfo(pkg, 0); true
    } catch (e: Exception) { false }

    fun fireTv(c: Context) = installed(c, FireWatch.AMAZON_HOME)
    fun googleTv(c: Context) = installed(c, FireWatch.GOOGLE_TV_HOME)

    /**
     * Whether the Home key opens Guest TV right now. Asked of Android's own resolver, not the role:
     * an Android TV emulator (Android 12) gave Guest TV the home role and still sent Home to its own
     * launcher, whose HOME entry carries a higher priority.
     */
    fun held(c: Context): Boolean {
        val ri = c.packageManager.resolveActivity(
            Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME), PackageManager.MATCH_DEFAULT_ONLY)
        return ri?.activityInfo?.packageName == c.packageName
    }

    /** Android says Guest TV is the default home (the role), whatever the Home key does. */
    fun chosen(c: Context): Boolean {
        if (Build.VERSION.SDK_INT < 29) return false
        val rm = c.getSystemService(RoleManager::class.java) ?: return false
        return rm.isRoleAvailable(RoleManager.ROLE_HOME) && rm.isRoleHeld(RoleManager.ROLE_HOME)
    }

    /**
     * "held", "fire" (Amazon keeps its home: the watch), "outranked" (chosen, but the TV's own home
     * still answers Home: the watch), "google_tv" (may need the watch too) or "ask".
     */
    fun state(c: Context): String = when {
        fireTv(c) -> "fire"
        held(c) -> "held"
        chosen(c) -> "outranked"
        googleTv(c) -> "google_tv"
        else -> "ask"
    }

    /** Opens Android's own chooser. Returns false when this TV offers none. */
    fun request(a: Activity, code: Int = REQUEST): Boolean = try {
        if (Build.VERSION.SDK_INT >= 29) {
            val rm = a.getSystemService(RoleManager::class.java)
            if (rm != null && rm.isRoleAvailable(RoleManager.ROLE_HOME)) {
                a.startActivityForResult(rm.createRequestRoleIntent(RoleManager.ROLE_HOME), code)
                true
            } else fallback(a)
        } else fallback(a)
    } catch (e: Exception) { fallback(a) }

    private fun fallback(a: Activity): Boolean = try {
        val settings = Intent(Settings.ACTION_HOME_SETTINGS)
        if (settings.resolveActivity(a.packageManager) != null) { a.startActivity(settings); true }
        else {
            // No Home settings screen: a Home intent with no default set makes Android ask "Select a home app".
            val home = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
            a.startActivity(Intent.createChooser(home, null)); true
        }
    } catch (e: Exception) { false }
}
