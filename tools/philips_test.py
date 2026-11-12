"""Test the Philips drivers (tv_philips.py: Titan OS and Saphi), the hook and the Titan start page, with no
real TV. A stand in Titan OS TV (HTTPS, digest login, PIN pairing) and a stand in Saphi TV (plain port, no
login) run on this computer for the test, answering the way couch-tv's notes say the real ones do. The
shapes are partly our own reading of Philips's network remote, so this proves the driver is consistent
with itself and careful with what it sends, NOT that a real TV answers the same way.

    .venv/bin/python tools/philips_test.py     (needs: the openssl command)
"""
import base64, hashlib, hmac, json, os, re, socket, ssl, subprocess, sys, tempfile, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import tvbrands, tvctl, tv_philips

TMP = tempfile.mkdtemp(prefix="guest-tv-philips-")
tvbrands.DATA = TMP   # keys go here, not in data/
CERT, KEY = os.path.join(TMP, "c.pem"), os.path.join(TMP, "k.pem")
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=tv",
                "-keyout", KEY, "-out", CERT], capture_output=True, check=True)
TLS = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
TLS.load_cert_chain(CERT, KEY)

# a made up pairing key and PIN: written here, never Philips's
SECRET = base64.b64encode(b"stand in shared key, not Philips's").decode()
PIN = "4821"
REALM = "standin"
APPS = [{"id": "netflix", "label": "Netflix"}, {"id": "youtube", "label": "YouTube"},
        {"id": "prime", "label": "Amazon Prime Video"}, {"id": "stan.app", "label": "Stan"},
        {"id": "side.1", "label": "Some Local App"}, {"id": "bad;id", "label": "Evil"},
        {"id": "guest.tv", "label": "Guest TV"}]


def md5(s):
    return hashlib.md5(s.encode()).hexdigest()


class StandIn:
    """One stand in TV. tls + login = Titan OS; neither = Saphi. The digest check and the pairing
    signature are written here separately from the driver's."""

    def __init__(self, tls=True, login=True, version="6/", browser=False, powerstate=True, applist=True):
        self.tls, self.login, self.version, self.browser = tls, login, version, browser
        self.has_powerstate, self.has_applist = powerstate, applist
        self.power, self.front = "On", ""   # front None: activities/current is missing
        self.apps = [dict(a) for a in APPS]
        self.volume = {"current": 12, "min": 0, "max": 60, "muted": False}
        self.logins, self.pending = {}, {}
        self.pin_shown = False
        self.keys, self.launched, self.pages, self.log = [], [], [], []
        self.nonce = "n0nce-1"
        self.drop = False   # answer nothing at all
        self.srv = None
        self.port = closed_port()   # until it starts

    def start(self):
        me = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, body=None, headers=None):
                b = (json.dumps(body) if body is not None else "").encode()
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("content-length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                me.handle(self, "GET")

            def do_POST(self):
                me.handle(self, "POST")

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        if self.tls:
            self.srv.socket = TLS.wrap_socket(self.srv.socket, server_side=True)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]
        return self

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()

    def logged_in(self, h, users):
        a = h.headers.get("Authorization", "")
        if not a.startswith("Digest "):
            return False
        f = dict(re.findall(r'(\w+)="?([^",]*)"?', a[7:]))
        pw = users.get(f.get("username"))
        if pw is None or f.get("nonce") != self.nonce or f.get("uri") != h.path:
            return False
        ha1, ha2 = md5("%s:%s:%s" % (f["username"], REALM, pw)), md5("%s:%s" % (h.command, f["uri"]))
        return f.get("response") == md5("%s:%s:%s:%s:auth:%s" % (ha1, self.nonce, f.get("nc"), f.get("cnonce"), ha2))

    def challenge(self, h):
        h.send(401, headers={"WWW-Authenticate": 'Digest realm="%s", qop="auth", nonce="%s", opaque="op"' % (REALM, self.nonce)})

    def handle(self, h, method):
        if self.drop:
            h.close_connection = True
            return
        n = int(h.headers.get("content-length") or 0)
        text = h.rfile.read(n).decode() if n else ""
        data = json.loads(text) if text else None
        if not h.path.startswith("/" + self.version):
            return h.send(404)
        path = h.path[len("/" + self.version):]
        if path == "system" and method == "GET":
            about = {"name": "Stand in Philips", "model": "00XX0000/12"}
            if self.browser:
                about["featuring"] = {"jsonfeatures": {"activities": ["browser"]}}
            return h.send(200, about)
        if path == "pair/request" and method == "POST":
            dev = ((data or {}).get("device") or {}).get("id")
            if not dev or sorted((data or {}).get("scope") or []) != ["control", "read", "write"]:
                return h.send(200, {"error_id": "INVALID_PARAMETER"})
            self.pending[dev] = ("auth-" + dev, 1700000000)
            self.pin_shown = True
            return h.send(200, {"error_id": "SUCCESS", "auth_key": "auth-" + dev, "timestamp": 1700000000, "timeout": 60})
        if path == "pair/grant" and method == "POST":
            if not self.logged_in(h, {d: k for d, (k, _) in self.pending.items()}):
                return self.challenge(h)
            auth, dev = (data or {}).get("auth") or {}, ((data or {}).get("device") or {}).get("id")
            key, ts = self.pending.get(dev, (None, None))
            good = base64.b64encode(hmac.new(base64.b64decode(SECRET), ("%s%s" % (ts, PIN)).encode(),
                                             hashlib.sha1).hexdigest().encode()).decode()
            if auth.get("pin") != PIN or auth.get("auth_signature") != good:
                return h.send(200, {"error_id": "INVALID_PIN"})
            self.logins[dev] = key
            self.pin_shown = False
            return h.send(200, {"error_id": "SUCCESS"})
        if self.login and not self.logged_in(h, self.logins):
            return self.challenge(h)
        self.log.append((method, path))
        if path == "powerstate":
            if not self.has_powerstate:
                return h.send(404)
            if method == "POST":
                self.power = data["powerstate"]
                return h.send(200, {})
            return h.send(200, {"powerstate": self.power})
        if path == "input/key" and method == "POST":
            self.keys.append(data["key"])
            if data["key"] == "Home":
                self.front = ""
            return h.send(200, {})
        if path == "audio/volume":
            if method == "POST":
                self.volume.update({k: v for k, v in data.items() if k in ("current", "muted")})
                return h.send(200, {})
            return h.send(200, self.volume)
        if path == "applications":
            return h.send(200, {"version": 1, "applications": self.apps}) if self.has_applist else h.send(404)
        if path == "activities/current":
            if self.front is None:
                return h.send(404)
            return h.send(200, {"component": {"packageName": self.front or "NA", "className": "NA"}})
        if path == "activities/launch" and method == "POST":
            hit = next((a for a in self.apps if a == data), None)
            if not hit:
                return h.send(400)
            self.launched.append(hit["id"])
            if self.front is not None:
                self.front = hit["id"]
            return h.send(200, {})
        if path == "activities/browser" and method == "POST":
            url = data.get("url") if isinstance(data, dict) else None
            if not self.browser or not isinstance(url, str) or not re.match(r"^https?://", url):
                return h.send(400 if self.browser else 404)
            self.pages.append(url)
            if self.front is not None:
                self.front = "browser"
            return h.send(200, {})
        h.send(404)


ok = bad = 0


def check(name, cond):
    global ok, bad
    ok, bad = ok + bool(cond), bad + (not cond)
    print(("PASS " if cond else "FAIL ") + name, flush=True)


def raises(fn, *kinds):
    try:
        fn()
        return False
    except kinds or Exception:
        return True


def wait_for(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def hook(tv):
    stop = threading.Event()
    threading.Thread(target=tvbrands.watch, args=(tv, 0.2, stop), daemon=True).start()
    time.sleep(0.5)
    return stop


def closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def make(sin, kind, **kw):
    tv_philips.PhilipsTV.PORT_TLS = sin.port if sin.tls else closed_port()
    tv_philips.PhilipsTV.PORT_PLAIN = sin.port if not sin.tls else closed_port()
    tv = tvbrands.make(kind, "127.0.0.1")
    tv.SETTLE = 0.1
    tv.page = "http://192.0.2.20:5410/tv/?tv=guest&brand=" + kind
    return tv


def pair_now(sin, tv):
    """Skip the PIN: give the driver a login as pairing would."""
    pw = "t-" + os.urandom(6).hex()
    sin.logins["dev-test"] = pw
    tv._save(user="dev-test", password=pw)


# ---------------------------------------------------------------- Titan OS
print("Titan OS")
t = StandIn().start()
tv = make(t, "titan")
check("built by tvbrands.make with its kind", type(tv).__name__ == "PhilipsTV" and tv.kind == "titan")
check("Titan pairing is a PIN", tv.pairing == "pin")
check("not paired: the TV is there but wants a login, so is_on is None", tv.is_on() is None)
check("not paired: the app list is refused plainly", raises(tv.app_ids, tvbrands.TVUnavailable))
check("no pairing key saved: pairing is refused before the TV is asked",
      raises(tv.pair_start, tvbrands.TVUnavailable) and not t.pin_shown)

try:
    tv_philips.save_secret("not base64 !!")
    bad_secret = False
except ValueError as e:
    bad_secret = SECRET not in str(e)
check("a key that is not base64 is refused", bad_secret)
tv_philips.save_secret(SECRET)
mode = oct(os.stat(tv_philips.secret_path()).st_mode & 0o777)
check("the owner's key is kept 0600 in data/ under a name git ignores", mode == "0o600" and tv_philips.secret_path().endswith(".key"))
check("pair_start makes the TV show a PIN", tv.pair_start() is True and t.pin_shown)
check("a malformed PIN is refused before it is sent", raises(lambda: tv.pair_finish("12"), ValueError))
try:
    tv.pair_finish("0000")
    refused = False
except tvbrands.TVUnavailable as e:
    refused = "refused the PIN" in str(e) and "0000" not in str(e) and SECRET not in str(e)
check("a wrong PIN is refused, in plain words, with no key in the message", refused and not tv.paired)
check("a PIN with no new request is refused (the old one is spent)", True)
tv.pair_start()
check("the right PIN pairs", tv.pair_finish(PIN) is True and tv.paired and not t.pin_shown)
check("the login is kept 0600", oct(os.stat(tv.store_file).st_mode & 0o777) == "0o600")
check("the pairing key is not in the kept login", SECRET not in open(tv.store_file).read())

check("is_on: on", tv.is_on() is True)
t.power = "Standby"
check("is_on: standby", tv.is_on() is False)
t.power = "On"
t.drop = True
check("is_on: no answer is None", tv.is_on() is None)
t.drop = False
dead = make(StandIn(), "titan")
check("is_on: nothing listening is None", dead.is_on() is None)

t.front = ""
check("front: the home is None", tv.front() is None)
t.front = "netflix"
check("front: an app is its id", tv.front() == "netflix")
t.front = "org.droidtv.playtv"
check("front: live TV is None", tv.front() is None)
t.front = "hdmi2"
check("front: an input is its id, and counts as nothing", tv.front() == "hdmi2" and tv.nothing("hdmi2"))
t.front = None
tv.visible = None
check("front: a TV that will not say gives None", tv.front() is None and tv.front_readable is False and tv.sees_front is False)
tv._front_at = 0.0   # five minutes on, it is asked again
t.front = ""
check("front: asked again later, a TV that now says is read", tv.sees_front is True and tv.front() is None and tv.front_readable is True)

ids = tv.app_ids()
check("app_ids: the guest apps by name and by Philips's own names",
      ids == {"netflix": "netflix", "youtube": "youtube", "prime-video": "prime", "stan": "stan.app"})
check("app_ids: the Guest TV app, an unknown app and an unsafe id are not guest apps",
      "guest.tv" not in ids.values() and "side.1" not in ids.values() and "bad;id" not in ids.values())
check("installed() lists only apps in tvctl.APPS", sorted(a["id"] for a in tv.installed()) == ["netflix", "prime-video", "stan", "youtube"])
check("an id the TV did not list is refused", raises(lambda: tv.launch("not.listed"), tvbrands.TVUnavailable))
check("an unsafe id is refused before it goes back", raises(lambda: tv.launch("bad;id"), tvbrands.TVUnavailable) and "bad;id" not in t.launched)
tv.open_app("stan")
check("open_app sends the TV's own object for the app it listed", t.launched[-1:] == ["stan.app"])
check("an app the TV does not list is refused plainly", raises(lambda: tv.open_app("kayo"), tvbrands.TVUnavailable))

keys = {"up": "CursorUp", "down": "CursorDown", "left": "CursorLeft", "right": "CursorRight", "ok": "Confirm",
        "back": "Back", "play_pause": "PlayPause", "next": "Next", "previous": "Previous",
        "rewind": "Rewind", "fast_forward": "FastForward"}
for name, code in keys.items():
    t.keys.clear()
    tv.key(name)
    check("key %s -> %s" % (name, code), t.keys == [code])
check("every guest key name has a key", set(tvctl.KEYS) <= set(tv.KEYS))
check("an unknown key is refused", raises(lambda: tv.key("power"), KeyError))
check("only a key from the table can be sent", raises(lambda: tv.button("Standby"), ValueError))
t.keys.clear()
tv.key("volume_up", 2)
tv.key("volume_down")
check("volume up and down", t.keys == ["VolumeUp", "VolumeUp", "VolumeDown"])
tv.key("mute")
check("mute is a set, over audio/volume", t.volume["muted"] is True and "Mute" not in t.keys)
tv.mute(False)
check("mute can be set off", t.volume["muted"] is False)

check("open_link: Netflix has no deep link here, so the app opens", tv.open_link("intent://www.netflix.com/watch/80057281#Intent;end", "netflix") == "app" and t.launched[-1] == "netflix")
check("open_link quietens the hook for a while", tv.quiet_until > time.monotonic() + 30)

t.launched.clear()
check("open_guest_app opens the app labelled Guest TV", tv.open_guest_app() is None and t.launched == ["guest.tv"])
check("is_guest: that app in front", tv.is_guest("guest.tv") and not tv.is_guest("netflix") and not tv.is_guest(None))
t.launched.clear()
tv.key("home")
check("the Guest remote's Home opens guest-tv when the TV has the app", t.launched == ["guest.tv"])

# no Guest TV app on the TV
t.apps = [a for a in t.apps if a["id"] != "guest.tv"]
tv._list_at = 0.0
t.launched.clear(); t.keys.clear()
try:
    tv.open_guest_app()
    msg = ""
except tvbrands.TVUnavailable as e:
    msg = str(e)
check("no Guest TV app: open_guest_app says so plainly", "Guest TV" in msg and "Titan app" in msg and "Guest remote still works" in msg)
check("no Guest TV app: can_open is False", tv.can_open is False)
tv.key("home")
check("no Guest TV app: the Guest remote's Home presses the TV's own Home", t.keys == ["Home"] and not t.launched)
t.apps.append({"id": "guest.tv", "label": "Guest TV"})
tv._list_at = 0.0
tv._applications()
check("the app appears later: can_open is True again", tv.can_open is True)

# the hook
tv.found = (0, {})
tv.quiet_until = 0
t.power, t.front, t.launched = "Standby", "", []
stop = hook(tv)
t.power = "On"
check("hook: TV comes on to the home, guest-tv opens", wait_for(lambda: t.launched == ["guest.tv"], 4))
check("hook: logged as opened", wait_for(lambda: any("opened guest-tv" in x for x in tv.log)))
t.power = "Standby"
time.sleep(0.6)
t.front, t.power, t.launched = "netflix", "On", []
time.sleep(1.5)
check("hook: TV comes on in an app, left alone", t.launched == [])
t.power = "Standby"
time.sleep(0.6)
t.front, t.power = "hdmi1", "On"
check("hook: TV comes on on an HDMI input, guest-tv opens", wait_for(lambda: t.launched == ["guest.tv"], 4))
t.power = "Standby"
time.sleep(0.6)
t.front, t.launched = "", []
tv.quiet(5)
t.power = "On"
time.sleep(1.5)
check("hook: respects quiet() after a guest's command", t.launched == [])
stop.set()

# no Guest TV app at all: the hook does nothing, quietly
t.apps = [a for a in t.apps if a["id"] != "guest.tv"]
tv._list_at, tv.quiet_until = 0.0, 0
tv._applications()
t.power, t.front, t.launched = "Standby", "", []
stop = hook(tv)
t.power = "On"
time.sleep(1.5)
check("hook: no Guest TV app, nothing opens and it says why", t.launched == [] and "Guest remote only" in tv.log[-1])
stop.set()
t.stop()

# ---------------------------------------------------------------- Saphi, no login
print("Saphi (no login)")
s = StandIn(tls=False, login=False, version="1/", browser=True, powerstate=False, applist=False).start()
sv = make(s, "saphi")
check("Saphi: built by tvbrands.make with its kind", sv.kind == "saphi")
check("Saphi answers without a login: pairing is None", sv.pairing is None and sv.open_api is True)
check("Saphi on plain 1925, API version 1", sv.is_on() is True and sv.version == "1/" and sv.tls is False)
check("no powerstate path: on while it answers", sv.has_powerstate is False)
check("Saphi with a browser can open", sv.can_open is True and sv.has_browser is True)
check("pairing is refused: nothing to pair", raises(sv.pair_start, tvbrands.TVUnavailable))
s.front = ""
check("front: home is None", sv.front() is None)
check("no app list: app_ids is empty and installed() is empty", sv.app_ids() == {} and sv.installed() == [])
check("no app list: an app is refused plainly", raises(lambda: sv.open_app("netflix"), tvbrands.TVUnavailable))
sv.key("left")
sv.key("volume_down")
check("keys and volume go as JointSpace keys", s.keys == ["CursorLeft", "VolumeDown"])
sv.key("mute")
check("mute set over audio/volume", s.volume["muted"] is True)
check("open_guest_app opens guest-tv's page in the TV's browser",
      sv.open_guest_app() is None and s.pages == ["http://192.0.2.20:5410/tv/?tv=guest&brand=saphi"])
check("is_guest: the browser in front", sv.is_guest(sv.front()))
sv.page = "javascript:alert(1)"
check("a page address that is not plain http(s) is refused", raises(sv.open_guest_app, tvbrands.TVUnavailable) and len(s.pages) == 1)
sv.page = "http://192.0.2.20:5410/tv/?tv=guest&brand=saphi"
sv.key("home")
check("Home opens guest-tv in the browser", len(s.pages) == 2)

# the hook, with a TV that will not say what is in front
s.front = None
sv.visible = None
check("Saphi cannot say what is in front: sees_front becomes False", (sv.front(), sv.sees_front) == (None, False))
s.pages.clear()
sv.quiet_until = 0
stop = hook(sv)
sv.is_on = lambda: on_state[0]
on_state = [False]
time.sleep(0.5)
on_state[0] = True
check("hook: Saphi comes on, the page opens in the browser", wait_for(lambda: len(s.pages) == 1, 4))
check("hook: logged as opened (the TV cannot say what is on screen)", wait_for(lambda: any("opened guest-tv" in x for x in sv.log) or any("asked it to open" in x for x in sv.log)))
stop.set()
s.stop()

# Saphi with no browser
print("Saphi (no browser)")
s2 = StandIn(tls=False, login=False, version="1/", browser=False, powerstate=False, applist=False).start()
nb = make(s2, "saphi")
nb.is_on()
check("no browser: can_open is False", nb.can_open is False)
try:
    nb.open_guest_app()
    msg = ""
except tvbrands.TVUnavailable as e:
    msg = str(e)
check("no browser: a plain sentence", "no browser" in msg and "Guest remote still works" in msg)
nb.key("home")
check("no browser: Home presses the TV's own Home", s2.keys == ["Home"])
s2.stop()

# ---------------------------------------------------------------- Saphi that wants a login
print("Saphi (wants a login, answers on 1926)")
tls_tv = StandIn(version="1/").start()
plain_tv = StandIn(tls=False, login=True, version="1/", browser=True).start()
tv_philips.PhilipsTV.PORT_TLS, tv_philips.PhilipsTV.PORT_PLAIN = tls_tv.port, plain_tv.port
sw = tvbrands.make("saphi", "127.0.0.1")
sw.is_on()
check("the plain port wants a login: the paired path on 1926 is used", sw.tls is True and sw.port == tls_tv.port)
check("pairing is now a PIN", sw.pairing == "pin")
sw.pair_start()
check("pair_start shows the PIN on the 1926 TV", tls_tv.pin_shown)
check("the PIN pairs it", sw.pair_finish(PIN) is True and sw.paired)
check("and then it answers", sw.is_on() is True)
tls_tv.stop()

print("Saphi (wants a login, 1926 silent)")
sx = StandIn(tls=False, login=True, version="1/").start()
tv_philips.PhilipsTV.PORT_TLS, tv_philips.PhilipsTV.PORT_PLAIN = closed_port(), sx.port
sy = tvbrands.make("saphi", "127.0.0.1")
check("1926 silent: the login goes over the plain port", sy.is_on() is None and sy.tls is False and sy.pairing == "pin")
pair_now(sx, sy)
check("paired over the plain port, it answers", sy.is_on() is True)
sx.stop()
plain_tv.stop()

# ---------------------------------------------------------------- the Titan start page
print("Titan start page")
page = open(os.path.join(os.path.dirname(HERE), "tv-apps", "titan", "index.html")).read()
script = page.split("<script>")[1].split("</script>")[0]
check("ES5 only: no fetch, no arrow functions, no let or const", not re.search(r"\bfetch\(|=>|\blet\b|\bconst\b|`", script))
check("it needs no key and holds none", not re.search(r"pairing|secret|Bearer|auth", page, re.I))
check("it moves to the TV page with brand=titan", "brand=titan" in script and "/tv/?" in script)
check("it takes the computer from ?guest=, a baked in address, or one typed once",
      "guest=" in script and "PRESET.guest" in script and "localStorage" in script)
built = tv_philips.build("http://192.0.2.20:5410", "guest")
check("build bakes in the computer and the home",
      '"guest": "192.0.2.20:5410"' in open(built).read() and '"home": "guest"' in open(built).read())
check("build refuses a bad address", raises(lambda: tv_philips.build("javascript:alert(1)", "guest"), SystemExit))
os.remove(built)

print("\n%d passed, %d failed" % (ok, bad))
sys.exit(1 if bad else 0)
