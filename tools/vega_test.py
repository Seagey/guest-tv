"""Test the Fire TV (Vega OS) driver (tv_vega.py) with no real stick. A stand-in stick runs on this
computer: a TCP port (the developer port), a DIAL service with a device description, and a fake `vega`
command put first on the PATH. No SSDP, nothing leaves 127.0.0.1.

    .venv/bin/python tools/vega_test.py
"""
import json, os, socketserver, stat, sys, tempfile, threading, time
import socket as socket_mod
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import tvbrands, tvctl, tv_vega

TMP = tempfile.mkdtemp(prefix="guest-tv-vega-")
tvbrands.DATA = TMP
BIN = os.path.join(TMP, "bin")
os.makedirs(BIN)
CLI_LOG = os.path.join(TMP, "cli.log")
open(CLI_LOG, "w").close()
FAKE = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["VEGA_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
if os.environ.get("VEGA_FAIL") and "launch-app" in sys.argv:
    print("error: app not installed"); sys.exit(1)
"""
exe = os.path.join(BIN, "vega")
open(exe, "w").write(FAKE)
os.chmod(exe, os.stat(exe).st_mode | stat.S_IXUSR)
os.environ["VEGA_LOG"] = CLI_LOG
os.environ["PATH"] = BIN + os.pathsep + os.environ["PATH"]


def cli_calls():
    return [json.loads(l) for l in open(CLI_LOG).read().splitlines() if l]


# ---------------------------------------------------------------- stand-in stick
class Port(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        pass


class Stick:
    def __init__(self):
        self.port = None
        self.srv = None
        self.dial_log = []
        self.known = {"Netflix", "YouTube", "GuestTV"}
        self.base = None
        self.http = None
        self.wake()

    def wake(self):
        self.srv = Port(("127.0.0.1", self.port or 0), Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def sleep(self):
        self.srv.shutdown()
        self.srv.server_close()

    def start_dial(self):
        stick = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path == "/dd.xml":
                    self.send_response(200)
                    self.send_header("Application-URL", stick.base or "http://127.0.0.1:%d/apps" % stick.http.server_address[1])
                    self.send_header("content-length", "7")
                    self.end_headers()
                    return self.wfile.write(b"<root/>")
                name = self.path.rsplit("/", 1)[-1]
                stick.dial_log.append(("GET", name, ""))
                self.send_response(200 if name in stick.known else 404)
                self.send_header("content-length", "0")
                self.end_headers()

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("content-length") or 0)).decode()
                name = self.path.rsplit("/", 1)[-1]
                stick.dial_log.append(("POST", name, body))
                self.send_response(201 if name in stick.known else 404)
                self.send_header("content-length", "0")
                self.end_headers()

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        return "http://127.0.0.1:%d/dd.xml" % self.http.server_address[1]


stick = Stick()
tv_vega.VegaTV.PORT = stick.port
tv = tv_vega.VegaTV("127.0.0.1")
tv.desc_url = stick.start_dial()
tv.SETTLE = 0.1
tv.GONE_IS_OFF = 0.3

passed = failed = 0


def check(name, ok, extra=""):
    global passed, failed
    if ok:
        passed += 1
        print("PASS", name)
    else:
        failed += 1
        print("FAIL", name, extra)


def raises(fn, exc):
    try:
        fn()
    except exc as e:
        return e
    return None


def see_page():
    tv.page_keys(0, timeout=0.01)


# ---------------------------------------------------------------- power
check("is_on: awake", tv.is_on() is True)
stick.sleep()
check("is_on: standby (port closed)", tv.is_on() is False)
real = tv_vega.socket.create_connection
def timed_out(*a, **k):
    raise socket_mod.timeout("no answer")
tv_vega.socket.create_connection = timed_out
check("is_on: gone (no answer)", tv.is_on() is None)
tv_vega.socket.create_connection = real
check("app_ids refuses when the TV does not answer", raises(tv.app_ids, tvbrands.TVUnavailable) is not None)
stick.wake()
check("is_on: awake again", tv.is_on() is True)

# ---------------------------------------------------------------- front and keys
check("front: nothing before the page polls", tv.front() is None and not tv.is_guest(tv.front()) and tv.nothing(tv.front()))
see_page()
check("front: guest-tv once the page polled", tv.front() == "guest-tv" and tv.is_guest(tv.front()))
tv.page_seen = time.monotonic() - 60
check("front: nothing again when the page went quiet", tv.front() is None)
err = raises(lambda: tv.key("ok"), tvbrands.TVUnavailable)
check("key refused while guest-tv is not in front, in plain words", err is not None and "Home on the phone remote" in str(err))

see_page()
base = tv.page_keys(0, timeout=0.01)["n"]
for name in ("up", "down", "left", "right", "ok", "back"):
    tv.key(name)
got = tv.page_keys(base, timeout=1)
check("every guest key reaches the page in order", got["keys"] == ["up", "down", "left", "right", "ok", "back"] and got["n"] == base + 6, got)
check("page_keys with nothing new waits then returns empty", tv.page_keys(got["n"], timeout=0.3) == {"n": got["n"], "keys": []})
result = {}
t = threading.Thread(target=lambda: result.update(tv.page_keys(got["n"], timeout=5)))
t.start()
time.sleep(0.3)
t0 = time.monotonic()
tv.key("ok")
t.join(3)
check("long poll wakes as soon as a key arrives", result.get("keys") == ["ok"] and time.monotonic() - t0 < 1.5, result)
check("a page remembering a number from before a restart starts again", tv.page_keys(9999, timeout=0.01)["n"] == got["n"] + 1)
tv.KEY_FRESH = 0.2
tv.key("up")
time.sleep(0.4)
check("a key nobody collected is not replayed later", tv.page_keys(0, timeout=0.01)["keys"] == [])
tv.KEY_FRESH = 10.0
tv.key("up", times=3)
check("times repeats a key", tv.page_keys(tv._n - 3, timeout=0.5)["keys"] == ["up"] * 3)
for name, word in (("volume_up", "volume"), ("volume_down", "volume"), ("mute", "mute")):
    e = raises(lambda n=name: tv.key(n), tvbrands.TVUnavailable)
    check("%s is the stick's own, said in a plain sentence" % name, e is not None and word in str(e) and "stick" in str(e))
check("volume() and mute() refuse", raises(lambda: tv.volume(True), tvbrands.TVUnavailable) and raises(tv.mute, tvbrands.TVUnavailable))
check("play_pause is not pressed, with a plain sentence", "arrows, OK and Back" in str(raises(lambda: tv.key("play_pause"), tvbrands.TVUnavailable)))
check("an unknown key name is a KeyError", raises(lambda: tv.key("format_disk"), KeyError) is not None)
check("push_key refuses names outside the table", raises(lambda: tv.push_key("volume_up"), KeyError) is not None)
check("every key name in KEYS is a name guest-tv has", set(tv_vega.KEYS) <= set(tvctl.KEYS))

# ---------------------------------------------------------------- opening guest-tv
open(CLI_LOG, "w").close()
tv.key("home")
calls = cli_calls()
check("home opens guest-tv through the CLI (connect, then launch-app)",
      calls == [["exec", "vda", "connect", "127.0.0.1:%d" % stick.port],
                ["device", "launch-app", "--appName", "app.guesttv.home.main", "-d", "127.0.0.1:%d" % stick.port]], calls)
check("the CLI route did not touch DIAL", not [d for d in stick.dial_log if d[0] == "POST"])
os.environ["VEGA_FAIL"] = "1"
stick.dial_log.clear()
tv.open_guest_app()
check("CLI failing falls back to DIAL (GuestTV)", ("POST", "GuestTV", "") in stick.dial_log, stick.dial_log)
del os.environ["VEGA_FAIL"]
saved_path = os.environ["PATH"]
os.environ["PATH"] = "/nonexistent"
stick.dial_log.clear()
tv.open_guest_app()
check("no CLI at all opens it through DIAL", ("POST", "GuestTV", "") in stick.dial_log)
stick.known.discard("GuestTV")
e = raises(tv.open_guest_app, tvbrands.TVUnavailable)
check("nothing works: refused in plain words", e is not None and "could not open guest-tv" in str(e), str(e))
stick.known.add("GuestTV")
os.environ["PATH"] = saved_path
tv.dial_base = None
tv.desc_url = None

# ---------------------------------------------------------------- apps and shows
tv.desc_url = "http://127.0.0.1:1/dd.xml"
tv.found = (0.0, {})
check("app_ids: DIAL address not answering raises", raises(tv.app_ids, tvbrands.TVUnavailable) is not None)
tv.dial_base = None
tv.desc_url = "http://203.0.113.9/dd.xml"
check("a DIAL address that is not the stick is refused", "itself" in str(raises(tv.app_ids, tvbrands.TVUnavailable)))
tv.desc_url = None
check("app_ids: no DIAL address written down means none to offer", tv.app_ids() == {})
open(tvbrands._token_file("vega-dial", "127.0.0.1"), "w").write(stick.http and "http://127.0.0.1:%d/dd.xml" % stick.http.server_address[1])
check("the owner's DIAL file is read", tv.app_ids() == {"netflix": "Netflix", "youtube": "YouTube"})
check("installed() lists only apps in the guest table", [a["id"] for a in tv.installed()] == ["netflix", "youtube"])
stick.known.discard("YouTube")
tv.found = (0.0, {})
check("an app the stick does not know is left out", tv.app_ids() == {"netflix": "Netflix"})
stick.known.add("YouTube")
tv.found = (0.0, {})
stick.dial_log.clear()
r = tv.open_link("https://www.netflix.com/title/80100172", "netflix")
check("Netflix title opens by id (show)", r == "show" and ("POST", "Netflix", "m=https%3A%2F%2Fwww.netflix.com%2Fwatch%2F80100172") in stick.dial_log, stick.dial_log)
r = tv.open_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube")
check("YouTube video opens by id (show)", r == "show" and ("POST", "YouTube", "v=dQw4w9WgXcQ") in stick.dial_log, stick.dial_log)
check("a title opened from the phone sets a long quiet time", tv.quiet_until > time.monotonic() + 30)
stick.dial_log.clear()
r = tv.open_link("https://www.netflix.com/browse", "netflix")
check("a Netflix link without a title just opens the app (app)", r == "app" and ("POST", "Netflix", "") in stick.dial_log, stick.dial_log)
check("an app Vega cannot reach is refused in plain words", "not on this TV" in str(raises(lambda: tv.open_app("stan"), tvbrands.TVUnavailable)))
check("launch refuses an id outside the table", raises(lambda: tv.launch("Evil/../x"), tvbrands.TVUnavailable) is not None)
check("_dial refuses an unsafe name", raises(lambda: tv._dial("a b;rm", "POST"), ValueError) is not None)
check("the CLI refuses an unsafe app id", raises(lambda: tv._cli_launch("x; rm -rf /"), ValueError) is not None)
check("spotify only opens, and is not here", raises(lambda: tv.spotify("x"), tvbrands.TVUnavailable) is not None)
check("pairing: none; can_open and sees_front", tv.pairing is None and tv.can_open and tv.sees_front)

# ---------------------------------------------------------------- the hook
tv.quiet_until = 0.0
open(CLI_LOG, "w").close()
tv.page_seen = 0.0
tv.dial_base = None
stick.sleep()
evt = threading.Event()
th = threading.Thread(target=tvbrands.watch, args=(tv,), kwargs={"every": 0.2, "stop": evt}, daemon=True)
th.start()
time.sleep(0.8)
check("hook: nothing opens while the stick is in standby", cli_calls() == [])
stick.wake()
for _ in range(30):
    if any(c[:2] == ["device", "launch-app"] for c in cli_calls()):
        break
    time.sleep(0.1)
check("hook: standby to on with nothing on screen opens guest-tv", any(c[:2] == ["device", "launch-app"] for c in cli_calls()), cli_calls())
tv.page_keys(0, timeout=0.01)   # the app starts and its page polls, so the hook sees it
time.sleep(0.8)
open(CLI_LOG, "w").close()
stick.sleep()
time.sleep(0.9)   # standby (and the dropout grace)
tv.page_keys(0, timeout=0.01)   # guest-tv still in front when the stick comes back
stick.wake()
time.sleep(1.2)
check("hook: leaves guest-tv alone when its page is already in front", cli_calls() == [], cli_calls())
tv.page_seen = 0.0
time.sleep(0.3)
stick.sleep()
time.sleep(0.9)
tv.quiet(5)   # a guest's command just ran
stick.wake()
time.sleep(1.2)
check("hook: respects quiet()", cli_calls() == [], cli_calls())
tv.quiet_until = 0.0
stick.sleep()
time.sleep(0.9)
stick.wake()
for _ in range(30):
    if cli_calls():
        break
    time.sleep(0.1)
check("hook: opens again once quiet time is over", any(c[:2] == ["device", "launch-app"] for c in cli_calls()), cli_calls())
evt.set()
th.join(8)
check("hook: stops when asked", not th.is_alive())
check("hook log says what it did", any("opened guest-tv" in l or "asked it to open guest-tv" in l or "left alone" in l for l in tv.log), tv.log)

# ---------------------------------------------------------------- the app files
sys.path.insert(0, tv_vega.VEGA_APP_DIR)
import importlib.util
spec = importlib.util.spec_from_file_location("mk", os.path.join(tv_vega.VEGA_APP_DIR, "make-config.py"))
mk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mk)
check("make-config: address and home id", mk.build("http://192.0.2.20:5410", "guest") == {"url": "http://192.0.2.20:5410", "tv": "guest"})
for bad in (("http://192.0.2.20:5410/x", "guest"), ("https://x", "guest"), ("http://192.0.2.20:5410", "Bad Id")):
    try:
        mk.build(*bad)
        check("make-config refuses %s" % (bad,), False)
    except SystemExit:
        check("make-config refuses %s" % (bad,), True)
app = open(os.path.join(tv_vega.VEGA_APP_DIR, "src", "App.tsx")).read()
check("App.tsx opens brand=vega&keys=1 with no key in the address", "brand=vega&keys=1" in app and "key=" not in app.replace("keys=1", ""))

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
