"""TV control for the Guest remote: keys, apps, volume, shows and Spotify, over ADB.

Only what a guest may do is here. No settings, no installs, no sign-ins, no shell from outside:
every command below is built from a fixed table, never from text a guest typed.

The TV's address: the home's `tv` (data/private.json or home.json), else settings.json "tv", else
the profile picker's "tv". An address, not a .local name (see profiles.py).
"""
import html, json, os, re, threading, time, urllib.parse, urllib.request

# The apps a guest may open. `jw` = JustWatch names for the show finder, `link` = how a show opens:
# "jw" the JustWatch Android TV link works, "app" only the app opens (from couch-tv's tested table).
APPS = [
    {"id": "netflix", "name": "Netflix", "package": "com.netflix.ninja", "jw": ["netflix", "netflixbasicwithads"], "link": "jw", "cold": True},
    {"id": "stan", "name": "Stan", "package": "au.com.stan.and", "jw": ["stan"], "link": "jw"},
    {"id": "disney-plus", "name": "Disney+", "package": "com.disney.disneyplus", "jw": ["disneyplus"], "link": "jw"},
    {"id": "prime-video", "name": "Prime Video", "package": "com.amazon.amazonvideo.livingroom", "jw": ["amazonprimevideo", "amazon"], "link": "jw"},
    {"id": "youtube", "name": "YouTube", "package": "com.google.android.youtube.tv", "jw": ["youtube"], "link": "jw"},
    {"id": "abc-iview", "name": "ABC iview", "package": "au.net.abc.iview", "jw": ["iview"], "link": "jw"},
    {"id": "sbs-on-demand", "name": "SBS On Demand", "package": "com.sbs.ondemand.tv", "jw": ["sbsondemand"], "link": "app"},
    {"id": "binge", "name": "Binge", "package": "au.com.streamotion.ares.tv", "jw": ["binge"], "link": "app"},
    {"id": "apple-tv", "name": "Apple TV", "package": "com.apple.atve.androidtv.appletv", "jw": ["appletvplus"], "link": "jw"},
    {"id": "paramount-plus", "name": "Paramount+", "package": "com.cbs.ca", "jw": ["paramountplus", "paramountpluspremium"], "link": "jw"},
    {"id": "9now", "name": "9Now", "package": "au.com.ninenow.ctv", "jw": ["ninenow"], "link": "jw"},
    {"id": "7plus", "name": "7plus", "package": "com.swm.live", "jw": ["sevenplus"], "link": "jw"},
    {"id": "10play", "name": "10play", "package": "au.com.tenplay", "jw": ["tenplay"], "link": "jw"},
    {"id": "kayo", "name": "Kayo", "package": "au.com.kayosports.tv", "jw": [], "link": "app"},
    {"id": "spotify", "name": "Spotify", "package": "com.spotify.tv.android", "jw": [], "link": "app"},
]
BY_ID = {a["id"]: a for a in APPS}
BY_JW = {j: a for a in APPS for j in a["jw"]}
KEYS = {"up": "DPAD_UP", "down": "DPAD_DOWN", "left": "DPAD_LEFT", "right": "DPAD_RIGHT", "ok": "DPAD_CENTER",
        "back": "BACK", "home": "HOME", "play_pause": "MEDIA_PLAY_PAUSE", "next": "MEDIA_NEXT",
        "previous": "MEDIA_PREVIOUS", "rewind": "MEDIA_REWIND", "fast_forward": "MEDIA_FAST_FORWARD",
        "volume_up": "VOLUME_UP", "volume_down": "VOLUME_DOWN", "mute": "VOLUME_MUTE"}


class TV:
    def __init__(self, ip, auth_timeout=8):
        self.ip = ip
        self.auth_timeout = auth_timeout   # longer the first time, while someone presses Allow on the TV
        self.dev = None
        self.lock = threading.Lock()
        self.pkgs = (0, set())

    def _connect(self):
        from adb_shell.adb_device import AdbDeviceTcp
        from adb_shell.auth.sign_pythonrsa import PythonRSASigner
        priv = open(os.path.expanduser("~/.android/adbkey")).read()
        pub = open(os.path.expanduser("~/.android/adbkey.pub")).read()
        d = AdbDeviceTcp(self.ip, 5555, default_transport_timeout_s=8)
        d.connect(rsa_keys=[PythonRSASigner(pub, priv)], auth_timeout_s=self.auth_timeout)
        self.dev = d

    def sh(self, cmd, t=20):
        with self.lock:
            for attempt in (1, 2):
                try:
                    if self.dev is None:
                        self._connect()
                    return self.dev.shell(cmd, timeout_s=t, read_timeout_s=t)
                except Exception:
                    try:
                        self.dev and self.dev.close()
                    except Exception:
                        pass
                    self.dev = None
                    if attempt == 2:
                        raise

    def installed(self):
        """The guest apps on this TV (checked every 10 minutes)."""
        at, pk = self.pkgs
        if time.time() - at > 600:
            out = self.sh("pm list packages", 15)
            pk = set(re.findall(r"package:(\S+)", out))
            self.pkgs = (time.time(), pk)
        return [a for a in APPS if a["package"] in pk]

    def front(self):
        out = self.sh("dumpsys activity activities | grep -m1 -E 'ResumedActivity'", 8)
        m = re.search(r"u0 ([^/\s]+)/", out)
        return m.group(1) if m else None

    def key(self, name, times=1):
        code = KEYS[name]   # KeyError for anything not in the table
        for _ in range(max(1, min(int(times), 10))):
            self.sh("input keyevent KEYCODE_" + code, 8)

    def open_app(self, app_id):
        a = BY_ID[app_id]
        self.sh("monkey -p %s -c android.intent.category.LEANBACK_LAUNCHER 1 >/dev/null 2>&1" % a["package"], 15)

    def open_link(self, uri, app_id):
        """A JustWatch intent:// link for one show, opened only in the app it belongs to."""
        a = BY_ID[app_id]
        uri = re.sub(r"[^A-Za-z0-9:/?#\[\]@!$&()*+,;=._~%-]", "", uri)   # no quotes or spaces reach the shell
        uri = re.sub(r"component=([^/;]+)/[^;]+", r"package=\1", uri)
        if uri.startswith("intent:") and "package=" not in uri and uri.endswith(";end"):
            uri = uri[:-4] + ";package=%s;end" % a["package"]   # Stan's links name no app; pin it to this one
        if not (uri.startswith("intent:") and "package=" + a["package"] in uri):
            uri = None
        if a.get("cold"):
            self.sh("am force-stop " + a["package"], 8)
        if uri:
            out = self.sh("am start -W '%s'" % uri, 25)
            if "Error" not in out:
                return "show"
        self.open_app(app_id)
        return "app"

    def spotify(self, query):
        """Search Spotify on the TV and play the top result. Spotify's TV app ignores search links and
        hides its screen from ADB, so this walks its Search page by keys, from a fresh start, as tested
        on 2 Nov 2026: up to the top bar, left to Search, OK, OK for the keyboard, type, back, down twice
        to the first top result, OK to open it, OK on Play. Returns True when Spotify says it is playing."""
        q = re.sub(r"[^\w -]", "", query)[:60].strip()
        self.sh("am start -S -W -n com.spotify.tv.android/com.spotify.app.androidtv.MainActivity", 30)
        time.sleep(5)
        for k, wait in (("UP", .4), ("UP", .4), ("UP", .4), ("LEFT", .4), ("CENTER", 2), ("CENTER", 1.5)):
            self.sh("input keyevent KEYCODE_DPAD_" + k, 8)
            time.sleep(wait)
        if q:
            self.sh("input text '%s'" % q.replace(" ", "%s"), 10)
            time.sleep(3)
        for k, wait in (("BACK", .6), ("DPAD_DOWN", .5), ("DPAD_DOWN", .5), ("DPAD_CENTER", 4), ("DPAD_CENTER", 4)):
            self.sh("input keyevent KEYCODE_" + k, 8)
            time.sleep(wait)
        return self.playing("com.spotify.tv.android")

    def playing(self, package):
        out = self.sh("dumpsys media_session | grep -A14 'package=%s' | grep -m1 'state=PlaybackState'" % package, 10)
        return "state=3" in out


_tvs = {}


def tv_for(ip):
    if ip not in _tvs:
        _tvs[ip] = TV(ip)
    return _tvs[ip]


# ---------------------------------------------------------------- where a show streams (JustWatch, AU)

JW = "https://apis.justwatch.com/graphql"
SEARCH = """
query($country: Country!, $language: Language!, $first: Int!, $filter: TitleFilter) {
  popularTitles(country: $country, first: $first, filter: $filter) {
    edges { node { id objectType content(country: $country, language: $language) { title originalReleaseYear }
      offers(country: $country, platform: ANDROID_TV) { monetizationType deeplinkURL(platform: ANDROID_TV)
        package { technicalName } } } } } }
"""


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def same_title(asked, found):
    """Is the title JustWatch found the one that was asked for? ("chill music" is not "Wind Chill".)"""
    import difflib
    a, f = norm(asked), norm(found)
    return a == f or (len(a) > 3 and (a in f or f in a)) or difflib.SequenceMatcher(None, a, f).ratio() > 0.85


def find(title, kind=None):
    """Best match for a title: {title, year, type, offers: [{app, link, free}]} or None."""
    flt = {"searchQuery": title[:80]}
    if kind in ("tv", "movie"):
        flt["objectTypes"] = ["SHOW" if kind == "tv" else "MOVIE"]
    body = json.dumps({"query": SEARCH, "variables": {"country": "AU", "language": "en", "first": 6, "filter": flt}}).encode()
    req = urllib.request.Request(JW, body, {"content-type": "application/json", "user-agent": "guest-tv/1"})
    data = json.loads(urllib.request.urlopen(req, timeout=15).read())
    edges = ((data.get("data") or {}).get("popularTitles") or {}).get("edges") or []
    if not edges:
        return None
    want = norm(title)
    edges.sort(key=lambda e: norm(e["node"]["content"]["title"]) != want)   # exact title first, else most popular
    n = edges[0]["node"]
    offers = []
    for o in n.get("offers") or []:
        a = BY_JW.get(o["package"]["technicalName"])
        if a and o["monetizationType"] in ("FLATRATE", "FREE", "ADS", "FAST") and a["id"] not in [x["app"] for x in offers]:
            offers.append({"app": a["id"], "link": html.unescape(o.get("deeplinkURL") or "") if a["link"] == "jw" else ""})
    return {"title": n["content"]["title"], "year": n["content"].get("originalReleaseYear"),
            "type": "tv" if n["objectType"] == "SHOW" else "movie", "offers": offers}
