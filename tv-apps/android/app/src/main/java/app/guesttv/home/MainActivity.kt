package app.guesttv.home

import android.app.Activity
import android.content.Intent
import android.content.pm.ResolveInfo
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.InputType
import android.util.DisplayMetrics
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.webkit.JavascriptInterface
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.GridLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors

/**
 * Guest TV on a Google TV, Android TV or Fire TV. It finds the guest-tv computer on the Wi-Fi by
 * itself (Finder.kt) and shows its welcome page (/tv/) full screen, with the TV's apps in the page's
 * app row through window.TVOS. If nothing answers, the owner types the computer's address with the
 * remote. Hold BACK, or press MENU, for the owner's settings: the home screen request and the opt in
 * Home button watch. Built from couch-tv's TV home app, cut down to what guest-tv needs.
 */
class MainActivity : Activity() {

    private enum class Mode { SEARCH, FORM, WEB, SETTINGS }

    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newCachedThreadPool()
    private val banners = ConcurrentHashMap<String, ByteArray>()
    private val prefs by lazy { getSharedPreferences("guest", MODE_PRIVATE) }

    private lateinit var root: FrameLayout
    private var web: WebView? = null
    private var panel: View? = null
    private var hint: View? = null
    private var mode = Mode.SEARCH
    private var beforeSettings = Mode.SEARCH
    private var pageReady = false
    private var loadFailed = false
    private var search = 0          // which search is current: an older one's answer is ignored
    private var backHeld = false    // BACK held down long enough to open the settings
    private var waitingForNet = false
    private var form: EditText? = null
    private var formNote: TextView? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        CrashGuard.install(this)
        if (intent?.hasExtra("guest") == true || intent?.hasExtra("bridge") == true) CrashGuard.reset(this)
        // Crashed twice in the last few minutes: stand aside for the TV's own home (CrashGuard.kt).
        if (CrashGuard.standingAside(this) && CrashGuard.openStockHome(this)) {
            finish()
            return
        }
        CrashGuard.started(this)
        main.postDelayed({ CrashGuard.settled(this) }, CrashGuard.SETTLE_MS)
        runCatching { WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG) }
        root = FrameLayout(this).apply { setBackgroundColor(GROUND) }
        setContentView(root)
        hideSystemBars()
        intent?.let { readExtras(it) }
        FireWatch.ensure(this)   // only where the owner chose the watch and a computer granted the setting
        io.execute { appList() }
        val netBack = object : android.net.ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: android.net.Network) {
                main.post { if (waitingForNet) find() else if (mode == Mode.WEB && loadFailed) find() }
            }
        }
        val cm = getSystemService(android.net.ConnectivityManager::class.java)
        if (Build.VERSION.SDK_INT >= 24) runCatching { cm?.registerDefaultNetworkCallback(netBack) }
        if (!online(cm)) {
            // Just switched on: Wi-Fi takes a few seconds. Wait for it rather than search an empty network.
            waitingForNet = true
            showSearch(waiting = true)
            main.postDelayed({ if (waitingForNet) find() }, NET_WAIT_MS)
        } else find()
    }

    private fun online(cm: android.net.ConnectivityManager?): Boolean {
        if (cm == null || Build.VERSION.SDK_INT < 23) return true
        val n = cm.activeNetwork ?: return false
        return cm.getNetworkCapabilities(n) != null
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.hasExtra("guest") || intent.hasExtra("bridge") || intent.hasExtra("tv")) {
            readExtras(intent)
            find()
            return
        }
        // HOME pressed while Guest TV is in front: back to the welcome page.
        if (mode == Mode.SETTINGS) closeSettings()
    }

    override fun onResume() {
        super.onResume()
        hideSystemBars()
        if (mode == Mode.SETTINGS) showSettings()   // back from Android's home chooser or Accessibility: show what changed
        else if (mode == Mode.WEB && loadFailed) find()
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == HomeRole.REQUEST && mode == Mode.SETTINGS) showSettings()
    }

    override fun onDestroy() {
        super.onDestroy()
        io.shutdownNow()
    }

    /**
     * What a computer can tell the app over ADB (tools/tv_app.py): "guest" (or couch-tv's "bridge"),
     * guest-tv's address, and "tv", the home to show when the computer has more than one.
     */
    private fun readExtras(i: Intent) {
        val e = prefs.edit()
        (i.getStringExtra("guest") ?: i.getStringExtra("bridge"))?.trim()?.let {
            if (it.isEmpty() || it == "none") e.remove("base")
            else Finder.normalise(it, BuildConfig.PORT)?.let { b -> e.putString("base", b); e.putString("given", b) }
        }
        i.getStringExtra("tv")?.trim()?.let {
            if (it.isEmpty()) e.remove("tv") else if (HOME_ID.matches(it)) e.putString("tv", it)
        }
        e.apply()
    }

    // ---------------------------------------------------------------- finding the computer

    /** The address given or saved last time first, then the TV's own Wi-Fi; the form if nothing answers. */
    private fun find() {
        waitingForNet = false
        val mine = ++search
        showSearch(waiting = false)
        val known = listOfNotNull(prefs.getString("given", null), prefs.getString("base", null)).distinct()
        io.execute {
            val found = known.firstOrNull { Finder.probe(it) } ?: Finder.search(BuildConfig.PORT)
            main.post {
                if (mine != search || isFinishing) return@post
                if (found != null) prefs.edit().putString("base", found).remove("given").apply()
                // The owner opened the settings while it looked: closing them looks again (quickly, now it is saved).
                if (mode == Mode.SETTINGS) { beforeSettings = Mode.SEARCH; return@post }
                if (found != null) {
                    showWeb(found)
                } else showForm("No guest-tv answered on this Wi-Fi. Type the guest-tv computer's address below.")
            }
        }
    }

    // ---------------------------------------------------------------- the welcome page

    private fun webView(): WebView? = web ?: try {
        makeWebView().also { web = it; root.addView(it, 0, MATCH); CrashGuard.install(this) }
    } catch (e: Throwable) {
        android.util.Log.w("guesttv", "WebView not ready: ${e.message}")
        null
    }

    private fun showWeb(base: String) {
        val w = webView() ?: run { showForm("This TV's web view is not ready yet. Try again in a moment."); return }
        mode = Mode.WEB
        loadFailed = false
        pageReady = false
        val tv = prefs.getString("tv", null)
        // No home given: the computer shows its own default home.
        w.loadUrl("$base/tv/" + if (tv.isNullOrEmpty()) "" else "?tv=$tv")
        val mine = search
        main.postDelayed({ if (mine == search && mode == Mode.WEB && !pageReady) find() }, PAGE_MS)
    }

    private fun makeWebView(): WebView = WebView(this).apply {
        setBackgroundColor(GROUND)
        isFocusable = true
        isFocusableInTouchMode = true
        overScrollMode = View.OVER_SCROLL_NEVER
        isVerticalScrollBarEnabled = false
        isHorizontalScrollBarEnabled = false
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.mediaPlaybackRequiresUserGesture = false
        settings.cacheMode = WebSettings.LOAD_DEFAULT
        settings.textZoom = 100
        addJavascriptInterface(Native(), "TVOS")
        webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView, url: String) {
                if (loadFailed || !url.startsWith("http") || mode != Mode.WEB) return
                pageReady = true
                removePanel()
                view.visibility = View.VISIBLE
                view.requestFocus()
                showHintOnce()
            }

            override fun onReceivedError(view: WebView, req: WebResourceRequest, err: WebResourceError) {
                if (req.isForMainFrame) pageFailed()
            }

            override fun onReceivedHttpError(view: WebView, req: WebResourceRequest, res: WebResourceResponse) {
                if (req.isForMainFrame && res.statusCode >= 400) pageFailed()
            }

            // The page never leaves the computer it came from.
            override fun shouldOverrideUrlLoading(view: WebView, req: WebResourceRequest) = true

            override fun shouldInterceptRequest(view: WebView, req: WebResourceRequest): WebResourceResponse? {
                val u = req.url
                if (u.host != "tvos.invalid" || u.pathSegments.firstOrNull() != "banner") return null
                val img = bannerImage(u.lastPathSegment ?: return null) ?: return null
                return WebResourceResponse("image/jpeg", null, ByteArrayInputStream(img)).apply {
                    responseHeaders = mapOf("Cache-Control" to "max-age=86400", "Access-Control-Allow-Origin" to "*")
                }
            }

            override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                root.removeView(view)
                view.destroy()
                web = null
                pageReady = false
                find()
                return true
            }
        }
    }

    /** The page did not load: the computer went off or moved. Look again (and ask, if it is gone). */
    private fun pageFailed() {
        if (loadFailed) return
        loadFailed = true
        pageReady = false
        web?.stopLoading()
        web?.visibility = View.INVISIBLE
        main.postDelayed({ if (mode == Mode.WEB && loadFailed) find() }, 2000)
    }

    private fun js(code: String) {
        web?.takeIf { pageReady && mode == Mode.WEB }?.evaluateJavascript(code, null)
    }

    /** What the welcome page can ask for: the TV's apps for its app row, and opening one. */
    inner class Native {
        @JavascriptInterface
        fun apps(): String {
            val out = JSONArray()
            for ((ri, label) in appList()) {
                val ai = ri.activityInfo
                out.put(JSONObject().apply {
                    put("package", ai.packageName)
                    put("label", label)
                    put("hasBanner", ai.banner != 0 || ai.applicationInfo.banner != 0)
                })
            }
            return out.toString()
        }

        @JavascriptInterface
        fun launch(pkg: String): Boolean = launchPackage(pkg)

        /** "held", "fire", "google_tv" or "ask" (HomeRole.kt). */
        @JavascriptInterface
        fun homeState(): String = HomeRole.state(this@MainActivity)

        @JavascriptInterface
        fun requestHome(): Boolean {
            main.post { HomeRole.request(this@MainActivity) }
            return true
        }

        @JavascriptInterface
        fun version(): String = BuildConfig.VERSION_NAME
    }

    // ---------------------------------------------------------------- keys

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        // Game controller A, Select and the number pad's Enter count as OK; controller B and Escape as BACK.
        val same = when (event.keyCode) {
            KeyEvent.KEYCODE_BUTTON_A, KeyEvent.KEYCODE_BUTTON_SELECT, KeyEvent.KEYCODE_NUMPAD_ENTER -> KeyEvent.KEYCODE_DPAD_CENTER
            KeyEvent.KEYCODE_BUTTON_B, KeyEvent.KEYCODE_ESCAPE -> KeyEvent.KEYCODE_BACK
            else -> null
        }
        if (same != null) {
            return dispatchKeyEvent(KeyEvent(event.downTime, event.eventTime, event.action, same, event.repeatCount,
                event.metaState, event.deviceId, event.scanCode, event.flags, event.source))
        }
        // MENU (Fire TV's remote) or a Settings key: the owner's settings.
        if (event.keyCode == KeyEvent.KEYCODE_MENU || event.keyCode == KeyEvent.KEYCODE_SETTINGS) {
            if (event.action == KeyEvent.ACTION_UP && mode != Mode.SETTINGS) openSettings()
            return true
        }
        if (event.keyCode == KeyEvent.KEYCODE_BACK) {
            // Held about a second: the owner's settings, on any remote.
            if (event.action == KeyEvent.ACTION_DOWN && (event.isLongPress || event.repeatCount >= LONG_BACK) && !backHeld) {
                backHeld = true
                if (mode != Mode.SETTINGS) openSettings()
                return true
            }
            if (event.action == KeyEvent.ACTION_UP) {
                if (backHeld) { backHeld = false; return true }
                when (mode) {
                    Mode.WEB -> js("window.tv && tv.back && tv.back()")   // the page decides what BACK means
                    Mode.SETTINGS -> closeSettings()
                    Mode.SEARCH, Mode.FORM -> if (!HomeRole.held(this)) moveTaskToBack(true)
                }
            }
            return true
        }
        // The form: the remote's number keys type straight into the address.
        if (mode == Mode.FORM && event.action == KeyEvent.ACTION_DOWN && form?.hasFocus() != true) {
            val ch = when (event.keyCode) {
                in KeyEvent.KEYCODE_0..KeyEvent.KEYCODE_9 -> ('0' + (event.keyCode - KeyEvent.KEYCODE_0)).toString()
                in KeyEvent.KEYCODE_NUMPAD_0..KeyEvent.KEYCODE_NUMPAD_9 -> ('0' + (event.keyCode - KeyEvent.KEYCODE_NUMPAD_0)).toString()
                KeyEvent.KEYCODE_PERIOD, KeyEvent.KEYCODE_NUMPAD_DOT -> "."
                else -> null
            }
            if (ch != null) { typeKey(ch); return true }
            if (event.keyCode == KeyEvent.KEYCODE_DEL) { typeKey("del"); return true }
        }
        return super.dispatchKeyEvent(event)
    }

    // ---------------------------------------------------------------- the owner's screens

    private fun showSearch(waiting: Boolean) {
        if (mode == Mode.SETTINGS) return
        mode = Mode.SEARCH
        web?.visibility = View.INVISIBLE
        val col = column()
        col.addView(title("Guest TV"))
        col.addView(body(if (waiting) "Waiting for the Wi-Fi to connect." else
            "Looking for the guest-tv computer on this Wi-Fi. This takes a few seconds."))
        col.addView(note("Make sure the computer is on and guest-tv is running on it."))
        val row = row()
        row.addView(button("Type the address") { showForm(null) })
        row.addView(button("Settings") { openSettings() })
        col.addView(row)
        setPanel(col)
        row.getChildAt(0).requestFocus()
    }

    private fun showForm(message: String?) {
        search++   // a search still running is no longer wanted
        waitingForNet = false
        mode = Mode.FORM
        web?.visibility = View.INVISIBLE
        val outer = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(px(64), px(44), px(64), px(36))
        }
        val left = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        left.addView(title("Type the computer's address"))
        left.addView(body("The guest-tv computer's number on this Wi-Fi, for example 192.0.2.10 (on a Mac: System Settings, Wi-Fi, Details). Use the remote's arrows and OK, or its number keys."))
        val field = EditText(this).apply {
            setSingleLine(true)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            imeOptions = EditorInfo.IME_ACTION_GO
            textSize = 30f
            setTextColor(TEXT)
            setHintTextColor(TEXT_3)
            hint = "Computer address"
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            setPadding(px(18), px(10), px(18), px(10))
            background = box(FLAP, 0)
            if (Build.VERSION.SDK_INT >= 21) showSoftInputOnFocus = false
            val saved = prefs.getString("base", null)
            setText(saved?.removePrefix("http://")?.removeSuffix(":${BuildConfig.PORT}") ?: "")
            setOnFocusChangeListener { v, has -> v.background = box(if (has) FLAP_2 else FLAP, if (has) px(3) else 0) }
            // OK on the field: the TV's own keyboard, for a name rather than a number.
            setOnClickListener {
                getSystemService(InputMethodManager::class.java)?.showSoftInput(this, 0)
            }
            setOnEditorActionListener { _, _, _ -> tryAddress(); true }
        }
        left.addView(field, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = px(14) })
        val msg = note(message ?: "")
        left.addView(msg)
        val actions = row()
        actions.addView(button("Connect") { tryAddress() })
        actions.addView(button("Search again") { find() })
        actions.addView(button("Settings") { openSettings() })
        left.addView(actions)
        outer.addView(left, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))

        val pad = GridLayout(this).apply { columnCount = 3 }
        // ":" for a port other than guest-tv's usual one; Clear and Delete on the last row.
        val keys = listOf("1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", ":", "clear", "del")
        for (k in keys) {
            val word = when (k) { "del" -> "Delete"; "clear" -> "Clear"; else -> null }
            pad.addView(button(word ?: k, size = if (word != null) 17f else 26f) { typeKey(k) },
                GridLayout.LayoutParams().apply {
                    width = px(if (k == "clear") 190 else 90); height = px(62)
                    if (word != null) columnSpec = GridLayout.spec(GridLayout.UNDEFINED, if (k == "clear") 2 else 1)
                    setMargins(px(5), px(5), px(5), px(5))
                })
        }
        outer.addView(pad, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
            gravity = Gravity.CENTER_VERTICAL
            leftMargin = px(32)
        })
        setPanel(outer)
        form = field   // after setPanel, which forgets the last screen's form
        formNote = msg
        pad.getChildAt(0).requestFocus()
    }

    private fun typeKey(k: String) {
        val f = form ?: return
        val t = f.text.toString()
        f.setText(when (k) { "del" -> t.dropLast(1); "clear" -> ""; else -> t + k })
        f.setSelection(f.text.length)
    }

    private fun tryAddress() {
        val typed = form?.text?.toString().orEmpty()
        val base = Finder.normalise(typed, BuildConfig.PORT)
        if (base == null) {
            formNote?.text = "That is not an address. It is four numbers with dots, like 192.0.2.10, or 192.0.2.10:5410 with a port."
            return
        }
        formNote?.text = "Checking $base ..."
        val mine = ++search
        io.execute {
            val ok = Finder.probe(base, 2500, 3000)
            main.post {
                if (mine != search || mode != Mode.FORM) return@post
                if (ok) {
                    prefs.edit().putString("base", base).apply()
                    showWeb(base)
                } else formNote?.text = "No guest-tv answered at $base. Check the computer is on, guest-tv is running, and this TV is on the same Wi-Fi."
            }
        }
    }

    private fun openSettings() {
        if (mode != Mode.SETTINGS) beforeSettings = mode
        prefs.edit().putBoolean("hinted", true).apply()
        hint?.let { root.removeView(it) }
        hint = null
        showSettings()
    }

    private fun closeSettings() {
        when (beforeSettings) {
            Mode.WEB -> {
                mode = Mode.WEB
                removePanel()
                if (pageReady) { web?.visibility = View.VISIBLE; web?.requestFocus() } else find()
            }
            Mode.FORM -> showForm(null)
            else -> find()
        }
    }

    private fun showSettings() {
        mode = Mode.SETTINGS
        web?.visibility = View.INVISIBLE
        val col = column()
        col.addView(title("Guest TV settings"))

        col.addView(heading("Home screen"))
        val state = HomeRole.state(this)
        col.addView(body(when (state) {
            "held" -> "Guest TV is this TV's home screen: the Home button opens the welcome page."
            "fire" -> "Fire TV always keeps Amazon's home. Turn on the Home button watch below so Home comes back to Guest TV."
            "outranked" -> "Android has Guest TV as the home screen, but this TV's own home still answers the Home button. Turn on the Home button watch below."
            "google_tv" -> "Make Guest TV the home screen. Google TV can still send Home to its own home: if it does, turn on the Home button watch below."
            else -> "Make Guest TV the home screen, so the Home button opens the welcome page."
        }))
        val first: View
        val homeRow = row()
        if (state == "ask" || state == "google_tv") {
            homeRow.addView(button("Make Guest TV the home screen") { HomeRole.request(this) })
        }
        val wanted = FireWatch.wanted(this)
        if (homeRow.childCount > 0) col.addView(homeRow)

        col.addView(heading("Home button watch"))
        col.addView(body(when {
            !wanted -> "Off. Turn it on only if the Home button, or switching the TV on, still opens the TV's own home."
            FireWatch.connected -> "On and watching. The TV's own home may flash up for a moment before Guest TV comes back."
            FireWatch.enabledInSettings(this) -> "On. Android has the watch switched on and will start it in a moment."
            else -> "One more step: in the TV's Settings, Accessibility (on some TVs Settings, System, Accessibility), switch on Guest TV Home button watch."
        }))
        val watchRow = row()
        watchRow.addView(button(if (wanted) "Home button watch: on" else "Home button watch: off") {
            FireWatch.setWanted(this, !wanted)
            showSettings()
        })
        if (wanted && !FireWatch.connected) {
            watchRow.addView(button("Open Accessibility settings") {
                runCatching { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
            })
        }
        col.addView(watchRow)

        col.addView(heading("guest-tv computer"))
        col.addView(body(prefs.getString("base", null)?.let { "Showing $it" } ?: "Not found yet."))
        val compRow = row()
        compRow.addView(button("Search again") { mode = Mode.SEARCH; find() })
        compRow.addView(button("Type the address") { showForm(null) })
        compRow.addView(button("Close") { closeSettings() })
        col.addView(compRow)
        col.addView(note("Guest TV ${BuildConfig.VERSION_NAME}. Hold Back, or press Menu, to open these settings again."))

        val scroll = ScrollView(this).apply { isFillViewport = true; isVerticalScrollBarEnabled = false; addView(col) }
        setPanel(scroll)
        first = homeRow.getChildAt(0) ?: watchRow.getChildAt(0)
        first.requestFocus()
    }

    /** A few seconds' note, the first times the welcome page opens: how the owner finds the settings. */
    private fun showHintOnce() {
        if (prefs.getBoolean("hinted", false) || hint != null) return
        val n = prefs.getInt("hints", 0)
        if (n >= 3) return
        prefs.edit().putInt("hints", n + 1).apply()
        val t = TextView(this).apply {
            text = "Guest TV settings: hold Back, or press Menu"
            setTextColor(TEXT)
            textSize = 16f
            setPadding(px(18), px(10), px(18), px(10))
            background = box(Color.argb(230, 0x14, 0x16, 0x1D), 0)
        }
        hint = t
        root.addView(t, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
            Gravity.BOTTOM or Gravity.END).apply { setMargins(0, 0, px(32), px(28)) })
        main.postDelayed({ if (hint === t) { root.removeView(t); hint = null } }, HINT_MS)
    }

    // ---------------------------------------------------------------- small view helpers

    private fun px(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun box(color: Int, stroke: Int) = GradientDrawable().apply {
        setColor(color)
        cornerRadius = px(10).toFloat()
        if (stroke > 0) setStroke(stroke, WARM)
    }

    private fun column() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(px(64), px(44), px(64), px(36))
    }

    private fun row() = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        setPadding(0, px(10), 0, px(4))
    }

    private fun title(s: String) = TextView(this).apply {
        text = s
        setTextColor(TEXT)
        textSize = 34f
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
    }

    private fun heading(s: String) = TextView(this).apply {
        text = s
        setTextColor(WARM)
        textSize = 19f
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        setPadding(0, px(18), 0, 0)
    }

    private fun body(s: String) = TextView(this).apply {
        text = s
        setTextColor(TEXT_2)
        textSize = 18f
        setPadding(0, px(6), 0, px(2))
        maxWidth = px(820)
    }

    private fun note(s: String) = TextView(this).apply {
        text = s
        setTextColor(TEXT_3)
        textSize = 15f
        setPadding(0, px(10), 0, px(6))
        maxWidth = px(820)
    }

    private fun button(label: String, size: Float = 17f, onClick: () -> Unit) = TextView(this).apply {
        text = label
        setTextColor(TEXT)
        textSize = size
        gravity = Gravity.CENTER
        isFocusable = true
        isClickable = true
        setPadding(px(20), px(10), px(20), px(10))
        background = box(FLAP, 0)
        setOnFocusChangeListener { v, has ->
            v.background = box(if (has) FLAP_2 else FLAP, if (has) px(3) else 0)
        }
        setOnClickListener { onClick() }
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
            rightMargin = px(14)
        }
    }

    private fun setPanel(v: View) {
        removePanel()
        panel = v
        v.setBackgroundColor(GROUND)
        root.addView(v, MATCH)
        hint?.bringToFront()
    }

    private fun removePanel() {
        panel?.let { root.removeView(it) }
        panel = null
        form = null
        formNote = null
    }

    private fun hideSystemBars() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.decorView.windowInsetsController?.let {
                it.hide(WindowInsets.Type.systemBars())
                it.systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = (
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or View.SYSTEM_UI_FLAG_FULLSCREEN or
                View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION)
        }
    }

    // ---------------------------------------------------------------- the TV's apps (from couch-tv's app)

    @Volatile private var appCache: List<Pair<ResolveInfo, String>>? = null

    private fun appList(): List<Pair<ResolveInfo, String>> = appCache ?: synchronized(this) {
        appCache ?: run {
            val q = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LEANBACK_LAUNCHER)
            packageManager.queryIntentActivities(q, 0)
                .filter { it.activityInfo.packageName != packageName }
                .distinctBy { it.activityInfo.packageName }
                .map { it to it.loadLabel(packageManager).toString() }
                .sortedBy { it.second.lowercase() }
                .also { appCache = it }
        }
    }

    private fun launchPackage(pkg: String): Boolean {
        val i = packageManager.getLeanbackLaunchIntentForPackage(pkg)
            ?: packageManager.getLaunchIntentForPackage(pkg)
            ?: return false
        return try {
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            main.post { runCatching { startActivity(i) } }
            true
        } catch (e: Exception) { false }
    }

    /** The app's TV banner as a JPEG, for the page's app row: memory, then disk, then drawn fresh. */
    private fun bannerImage(pkg: String): ByteArray? {
        banners[pkg]?.let { return it }
        val ri = appList().firstOrNull { it.first.activityInfo.packageName == pkg }?.first ?: return null
        val version = try { packageManager.getPackageInfo(pkg, 0).lastUpdateTime } catch (e: Exception) { 0L }
        val file = java.io.File(java.io.File(filesDir, "banners").apply { mkdirs() }, "$pkg-$version.jpg")
        val bytes = if (file.exists()) file.readBytes() else bannerBytes(ri)?.also { file.writeBytes(it) }
        if (bytes != null) banners[pkg] = bytes
        return bytes
    }

    private fun sharp(pkg: String, res: Int): Drawable? {
        if (res == 0) return null
        return try {
            packageManager.getResourcesForApplication(pkg).getDrawableForDensity(res, DisplayMetrics.DENSITY_XXXHIGH, null)
        } catch (e: Exception) { null }
    }

    private fun bannerBytes(ri: ResolveInfo): ByteArray? {
        val banner = sharp(ri.activityInfo.packageName, ri.activityInfo.bannerResource)
            ?: ri.activityInfo.loadBanner(packageManager)
            ?: ri.activityInfo.applicationInfo.loadBanner(packageManager)
        val bmp = Bitmap.createBitmap(640, 360, Bitmap.Config.ARGB_8888)
        val c = Canvas(bmp)
        c.drawColor(FLAP)
        if (banner != null) {
            banner.setBounds(0, 0, 640, 360)
            banner.draw(c)
        } else {
            iconTile(sharp(ri.activityInfo.packageName, ri.activityInfo.iconResource) ?: ri.loadIcon(packageManager), c)
        }
        return ByteArrayOutputStream().also { bmp.compress(Bitmap.CompressFormat.JPEG, 90, it); bmp.recycle() }.toByteArray()
    }

    /** Apps with no TV banner still get a full tile: the icon's own edge colour fills it, the logo in the middle. */
    private fun iconTile(icon: Drawable, c: Canvas) {
        val n = 432
        val sq = Bitmap.createBitmap(n, n, Bitmap.Config.ARGB_8888)
        val sc = Canvas(sq)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && icon is android.graphics.drawable.AdaptiveIconDrawable) {
            icon.background?.apply { setBounds(0, 0, n, n); draw(sc) }
            icon.foreground?.apply { setBounds(0, 0, n, n); draw(sc) }
        } else {
            icon.setBounds(0, 0, n, n)
            icon.draw(sc)
        }
        val edge = sq.getPixel(2, n / 2)
        var l = n; var t = n; var r = 0; var b = 0
        for (y in 0 until n step 2) for (x in 0 until n step 2) {
            val px = sq.getPixel(x, y)
            val d = Math.abs(Color.red(px) - Color.red(edge)) + Math.abs(Color.green(px) - Color.green(edge)) +
                Math.abs(Color.blue(px) - Color.blue(edge))
            if (d > 60 && Color.alpha(px) > 128) { l = minOf(l, x); t = minOf(t, y); r = maxOf(r, x); b = maxOf(b, y) }
        }
        if (r <= l || b <= t) { l = n / 4; t = n / 4; r = n * 3 / 4; b = n * 3 / 4 }
        val s = minOf(150f / (b - t), 440f / (r - l)).coerceIn(0.5f, 3f)
        val size = (n * s).toInt()
        val left = (320 - (l + r) / 2f * s).toInt()
        val top = (180 - (t + b) / 2f * s).toInt()
        c.drawColor(edge)
        val p = android.graphics.Paint(android.graphics.Paint.FILTER_BITMAP_FLAG)
        c.drawBitmap(sq, null, android.graphics.Rect(left, top, left + size, top + size), p)
        sq.recycle()
    }

    companion object {
        /** A home id as guest-tv names them: small letters, digits and dashes. */
        private val HOME_ID = Regex("[a-z0-9-]{1,32}")
        private const val NET_WAIT_MS = 15_000L
        private const val PAGE_MS = 20_000L     // a page that has not loaded by then: look for the computer again
        private const val HINT_MS = 9_000L
        private const val LONG_BACK = 8         // key repeats, about a second of holding BACK
        private val MATCH = FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        // guest-tv's colours (web/tv.css)
        private val GROUND = Color.parseColor("#14161D")
        private val FLAP = Color.parseColor("#1F222C")
        private val FLAP_2 = Color.parseColor("#2A2E3B")
        private val TEXT = Color.parseColor("#F7F6F3")
        private val TEXT_2 = Color.parseColor("#C9C7C1")
        private val TEXT_3 = Color.parseColor("#8E8D88")
        private val WARM = Color.parseColor("#FFD89A")
    }
}
