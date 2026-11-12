"""Test the Roku driver (tv_roku.py), the hook, and the Roku channel's build and install, with no real
Roku. A stand-in Roku runs on this computer (127.0.0.1 only), answering Roku's External Control Protocol
the way Roku's documentation says a Roku does (ported from couch-tv's tests/roku_standin.py), and a
stand-in developer installer asks for HTTP digest sign in as rokudev, as a Roku in Developer Mode does.

    .venv/bin/python tools/roku_test.py
"""
import hashlib, json, os, sys, tempfile, threading, time, urllib.parse, zipfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import tvbrands, tvctl, tv_roku

TMP = tempfile.mkdtemp(prefix="guest-tv-roku-")
tvbrands.DATA = TMP
tv_roku.BUILD = os.path.join(TMP, "build")
tv_roku.ZIP = os.path.join(tv_roku.BUILD, "guest-tv-roku.zip")

# ---------------------------------------------------------------- the stand-in Roku
APPS = [("12", "Netflix"), ("837", "YouTube"), ("13", "Prime Video"), ("99001", "Stan"),
        ("99002", "SBS On Demand"), ("dev", "Guest TV"), ("5", "Some Local App"), ("../x", "Kayo")]
ROKU = {"power": "PowerOn", "active": ("12", "Netflix"), "up": True, "limited": False, "apps": list(APPS),
        "log": [], "say_power": True}


class Ecp(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, body="", ctype="text/xml"):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if not ROKU["up"]:
            return   # no answer: the connection just closes
        path = self.path.lstrip("/")
        if path == "query/device-info":
            pm = "<power-mode>%s</power-mode>" % ROKU["power"] if ROKU["say_power"] else ""
            return self.reply(200, "<device-info><model-name>Stand-in Roku TV</model-name>"
                                   "<software-version>14.1.0</software-version><is-tv>true</is-tv>%s</device-info>" % pm)
        if path == "query/active-app":
            rid, name = ROKU["active"]
            inner = '<app id="%s">%s</app>' % (rid, name) if rid else "<app>Roku</app>"
            return self.reply(200, "<active-app>%s</active-app>" % inner)
        if path == "query/apps":
            return self.reply(200, "<apps>%s</apps>" % "".join(
                '<app id="%s" type="appl" version="1.0">%s</app>' % (i, n) for i, n in ROKU["apps"]))
        self.reply(404)

    def do_POST(self):
        if not ROKU["up"]:
            return
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        full = self.path.lstrip("/")
        path = urllib.parse.urlparse(full).path
        if ROKU["limited"] and path.startswith(("keypress/", "launch/")):
            ROKU["log"].append(full + " [403]")
            return self.reply(403, "Forbidden", "text/plain")
        if not path.startswith(("keypress/", "launch/")):
            return self.reply(404)
        ROKU["log"].append(full)
        if path.startswith("launch/"):
            rid = path.split("/", 1)[1]
            name = dict(ROKU["apps"]).get(rid)
            if name is None:
                return self.reply(404)
            ROKU["active"] = (rid, name)
        elif path == "keypress/Home":
            ROKU["active"] = ("", "Roku")
        self.reply(200)


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


ecp = serve(Ecp)
tv_roku.RokuTV.PORT = ecp.server_address[1]
tv_roku.RokuTV.SETTLE = 0.2

# ---------------------------------------------------------------- the stand-in developer installer
PASSWORD = "not-a-real-password"
INSTALLER = {"received": []}


class Installer(BaseHTTPRequestHandler):
    """POST /plugin_install with digest auth (RFC 2617, qop=auth, MD5), form fields archive and mysubmit."""

    def log_message(self, *a):
        pass

    def challenge(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Digest realm="rokudev", qop="auth", nonce="abc123", opaque="xyz", algorithm=MD5')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Digest "):
            return self.challenge()
        f = {k.strip(): v.strip().strip('"') for k, v in (p.split("=", 1) for p in auth[7:].split(","))}
        ha1 = hashlib.md5(("rokudev:rokudev:" + PASSWORD).encode()).hexdigest()
        ha2 = hashlib.md5(("POST:" + f["uri"]).encode()).hexdigest()
        want = hashlib.md5(("%s:%s:%s:%s:%s:%s" % (ha1, f["nonce"], f["nc"], f["cnonce"], f["qop"], ha2)).encode()).hexdigest()
        if f.get("username") != "rokudev" or f.get("response") != want or self.path != "/plugin_install":
            return self.challenge()
        INSTALLER["received"].append(body)
        if b'name="mysubmit"\r\n\r\nReplace' in body and b'name="archive"' in body:
            page = b'<html><body><font color="red">Install Success.</font></body></html>'
        elif b'name="mysubmit"\r\n\r\nDelete' in body:
            page = b'<html><body><font color="red">Delete Succeeded.</font></body></html>'
        else:
            page = b'<html><body><font color="red">Missing fields</font></body></html>'
        self.send_response(200)
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)


inst = serve(Installer)
tv_roku.RokuTV.DEV_PORT = inst.server_address[1]

ok = bad = 0


def check(name, cond):
    global ok, bad
    ok, bad = ok + bool(cond), bad + (not cond)
    print(("PASS " if cond else "FAIL ") + name, flush=True)


def raises(fn, kind=Exception, words=""):
    try:
        fn()
        return False
    except kind as e:
        return words.lower() in str(e).lower()
    except Exception:
        return False


def wait_for(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def launches():
    return [x for x in ROKU["log"] if x.startswith("launch/")]


# ---------------------------------------------------------------- the driver
print("Roku driver")
tv = tvctl.tv_for("127.0.0.1", "roku")
check("tv_kind roku gives the Roku driver", isinstance(tv, tv_roku.RokuTV) and tv.kind == "roku")
check("no pairing on a Roku", tv.pairing is None)
check("PowerOn is on", tv.is_on() is True)
ROKU["power"] = "Ready"
check("Ready (standby) is off", tv.is_on() is False)
ROKU["power"] = "DisplayOff"
check("DisplayOff is off", tv.is_on() is False)
ROKU["say_power"] = False
check("a Roku that does not say its power mode is on", tv.is_on() is True)
ROKU["say_power"], ROKU["power"] = True, "PowerOn"
ROKU["up"] = False
check("not answering is None", tv.is_on() is None)
check("not answering: the app list says so", raises(tv.installed, tvbrands.TVUnavailable))
check("not answering: front() is None (unknown)", tv.front() is None)
ROKU["up"] = True
check("guest apps found by Roku id and by name, the unsafe id from the TV refused",
      [a["id"] for a in tv.installed()] == ["netflix", "stan", "prime-video", "youtube", "sbs-on-demand"])
check("guest-tv's own channel is never offered as an app", "dev" not in tv.app_ids().values())
check("front() names the channel on screen", tv.front() == "12")
ROKU["active"] = ("", "Roku")
check("Roku's home is \"\" and counts as nothing", tv.front() == "" and tv.nothing(""))
ROKU["active"] = ("tvinput.hdmi1", "HDMI 1")
check("an input counts as nothing", tv.nothing(tv.front()))
ROKU["active"] = ("../../x", "Odd")
check("an unsafe id on screen is not passed on", tv.front() is None)
check("unknown (None) is not nothing, so the hook leaves it alone", not tv.nothing(None))
check("an app is not nothing", not tv.nothing("12"))
check("guest-tv on screen is the dev channel", tv.is_guest("dev") and not tv.is_guest("12"))

ROKU["log"].clear()
for k in [k for k in tvctl.KEYS if k not in ("home", "mute", "volume_up", "volume_down")]:
    tv.key(k)
tv.key("volume_up", 2)
tv.key("volume_down")
tv.key("mute")
tv.key("home")
want = ["keypress/Up", "keypress/Down", "keypress/Left", "keypress/Right", "keypress/Select", "keypress/Back",
        "keypress/Play", "keypress/Fwd", "keypress/Rev", "keypress/Rev", "keypress/Fwd",
        "keypress/VolumeUp", "keypress/VolumeUp", "keypress/VolumeDown", "keypress/VolumeMute", "launch/dev"]
check("every guest key goes out as its ECP key (home opens guest-tv)", ROKU["log"] == want)
check("a key outside the table is refused", raises(lambda: tv.key("power"), KeyError))
check("a raw ECP key that is not a guest key is refused", raises(lambda: tv.button("PowerOff"), KeyError))

ROKU["log"].clear()
tv.open_app("stan")
check("open Stan by the id the Roku listed", ROKU["log"] == ["launch/99001"] and ROKU["active"][0] == "99001")
check("an app not on the Roku is refused", raises(lambda: tv.open_app("kayo"), tvbrands.TVUnavailable, "not on this TV"))
check("a bad id never reaches the TV", raises(lambda: tv.launch("12/../keypress/PowerOff"), tvbrands.TVUnavailable)
      and ROKU["log"] == ["launch/99001"])

how = tv.open_link("https://www.netflix.com/au/title/80057281", "netflix")
check("Netflix title with the deep link", how == "show" and ROKU["log"][-1] == "launch/12?contentId=80057281&mediaType=series")
how = tv.open_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube")
check("YouTube video with the deep link", how == "show" and ROKU["log"][-1] == "launch/837?contentId=dQw4w9WgXcQ&mediaType=live")
how = tv.open_link("intent://www.stan.com.au/watch/123#Intent;end", "stan")
check("Stan link: Stan opens", how == "app" and ROKU["log"][-1] == "launch/99001")
how = tv.open_link("https://www.netflix.com/title/123;rm", "netflix")
check("only the digits of a Netflix id go out", ROKU["log"][-1] == "launch/12?contentId=123&mediaType=series")
check("open_link keeps the hook quiet", tv.quiet_until > time.monotonic() + 30)

tv.page = "http://192.0.2.10:5410/tv/?tv=guest&brand=roku"
tv.open_guest_app()
check("open_guest_app launches the dev channel with the home", ROKU["log"][-1] == "launch/dev?home=guest")
tv.page = "http://192.0.2.10:5410/tv/?tv=Bad%20Home&brand=roku"
tv.open_guest_app()
check("a home that is not a plain id is left out", ROKU["log"][-1] == "launch/dev")
tv.page = None
ROKU["apps"] = [a for a in APPS if a[0] != "dev"]
check("guest-tv's channel not installed: said plainly",
      raises(tv.open_guest_app, tvbrands.TVUnavailable, "guest-tv's Roku channel is not on this Roku"))
ROKU["apps"] = list(APPS)

# Control by mobile apps on a limiting mode
ROKU["limited"] = True
check("limited: a key is refused with the plain help", raises(lambda: tv.key("up"), tv_roku.ECPLimited, "Control by mobile apps"))
check("limited: said in ecp_status", tv.ecp_status()["limited"] and "Permissive" in tv.ecp_status()["message"])
check("limited: the power state still reads", tv.is_on() is True)
check("limited: opening guest-tv says why", raises(tv.open_guest_app, tv_roku.ECPLimited, "Control by mobile apps"))
ROKU["limited"] = False
tv.key("up")
check("the setting changed: it clears by itself", tv.ecp_status()["limited"] is False)

# ---------------------------------------------------------------- the hook
print("hook")


def hook(t):
    stop = threading.Event()
    threading.Thread(target=tvbrands.watch, args=(t, 0.2, stop), daemon=True).start()
    time.sleep(0.5)
    return stop


tv.quiet_until = 0
tv.page = "http://192.0.2.10:5410/tv/?tv=guest&brand=roku"
ROKU["power"], ROKU["active"] = "Ready", ("", "Roku")
ROKU["log"].clear()
stop = hook(tv)
ROKU["power"] = "PowerOn"
check("TV comes on to Roku's home: guest-tv opens", wait_for(lambda: launches() == ["launch/dev?home=guest"]))
ROKU["power"] = "Ready"
time.sleep(0.5)
ROKU["active"], ROKU["power"] = ("12", "Netflix"), "PowerOn"
time.sleep(1.5)
check("TV comes on in Netflix: left alone", launches() == ["launch/dev?home=guest"])
ROKU["power"] = "Ready"
time.sleep(0.5)
ROKU["active"] = ("", "Roku")
tv.quiet()
ROKU["power"] = "PowerOn"
time.sleep(1.5)
check("a guest command just ran: left alone", launches() == ["launch/dev?home=guest"])
ROKU["power"] = "Ready"
time.sleep(0.5)
tv.quiet_until = 0
ROKU["active"], ROKU["power"] = ("tvinput.hdmi2", "HDMI 2"), "PowerOn"
check("TV comes on to an input: guest-tv opens", wait_for(lambda: len(launches()) == 2))
ROKU["up"] = False
time.sleep(0.6)
ROKU["up"], ROKU["active"] = True, ("", "Roku")
check("back on the network after being gone: guest-tv opens", wait_for(lambda: len(launches()) == 3, 4))
stop.set()
check("the watcher wrote down that it opened guest-tv", any("opened guest-tv" in x for x in tv.log))

# ---------------------------------------------------------------- the channel: build and install
print("channel")
ZIP = tv_roku.build("http://192.0.2.10:5410/", "guest")
with zipfile.ZipFile(ZIP) as z:
    names = z.namelist()
    cfg = json.loads(z.read("config.json"))
    manifest = z.read("manifest").decode()
    everything = b"".join(z.read(n) for n in names)
check("the zip starts with the manifest", names[0] == "manifest")
check("the manifest names the channel and takes a launch while open",
      "title=Guest TV" in manifest and "supports_input_launch=1" in manifest and "ui_resolutions=fhd" in manifest)
need = ["source/main.brs", "components/WelcomeScene.xml", "components/WelcomeScene.brs", "components/Fetch.xml",
        "components/Fetch.brs", "fonts/Inter-Regular.ttf", "fonts/Inter-Medium.ttf", "fonts/Antonio-Light.ttf",
        "images/icon_focus_hd.png", "images/icon_focus_fhd.png", "images/splash_fhd.jpg", "images/ui/scrim.png",
        "images/ui/panel.9.png", "config.json"]
check("the channel's files are all in it", all(n in names for n in need))
check("the computer's address and the home are baked in", cfg == {"url": "http://192.0.2.10:5410", "home": "guest"})
check("no key and no password in the zip", set(cfg) == {"url", "home"} and PASSWORD.encode() not in everything
      and not [n for n in names if n.endswith(".key") or n.split("/")[-1].startswith(".")])
check("under Roku's 4 MB limit", os.path.getsize(ZIP) < tv_roku.SIZE_LIMIT)
check("a bad address or home is refused", raises(lambda: tv_roku.build("http://x;rm", "guest"), SystemExit)
      and raises(lambda: tv_roku.build("http://192.0.2.10:5410", "Guest Home"), SystemExit))
brs = open(os.path.join(tv_roku.CHANNEL, "components", "Fetch.brs")).read()
check("the channel sends Content-Type: application/json (the computer refuses POSTs without it)",
      'addHeader("Content-Type", "application/json")' in brs)
scene = open(os.path.join(tv_roku.CHANNEL, "components", "WelcomeScene.brs")).read()
check("the channel reads /api/tv/native and opens apps with POST /api/tv/app",
      '"/api/tv/native"' in scene and '"/api/tv/app"' in scene and '"/api/tv/apps"' in scene)

check("install: the right password installs", tv_roku.install("127.0.0.1", "http://192.0.2.10:5410", "guest", PASSWORD))
got = INSTALLER["received"][-1]
check("install: the zip went up with Replace", b'filename="guest-tv-roku.zip"' in got and b"\r\n\r\nReplace" in got)
check("install: a wrong password is refused", raises(lambda: tv_roku.install("127.0.0.1", "http://192.0.2.10:5410", "guest", "nope"), SystemExit))
os.environ["ROKU_DEV_PASSWORD"] = PASSWORD
check("install: the password from ROKU_DEV_PASSWORD", tv_roku.install("127.0.0.1", "http://192.0.2.10:5410", "guest"))
check("uninstall: Delete", tv_roku.uninstall("127.0.0.1") and b"\r\n\r\nDelete" in INSTALLER["received"][-1])
del os.environ["ROKU_DEV_PASSWORD"]
check("SETUP has the Developer Mode keys and Control by mobile apps",
      "Home three times, Up twice, Right, Left, Right, Left, Right" in tv_roku.SETUP and "Control by mobile apps" in tv_roku.SETUP)

ecp.shutdown()
inst.shutdown()
print("\n%d passed, %d failed" % (ok, bad))
sys.exit(1 if bad else 0)
