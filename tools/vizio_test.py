"""Test the VIZIO driver (tv_vizio.py) and the hook, with no real TV and no Claude. A stand-in VIZIO runs
on this computer over HTTPS with a throwaway certificate, answering the way couch-tv's notes (public
notes on the SmartCast API) say a real one does. It proves the driver is consistent with itself and
safe with what it sends, not that a real VIZIO answers the same way.

    .venv/bin/python tools/vizio_test.py
"""
import json, os, ssl, subprocess, sys, tempfile, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import tvbrands, tvctl, tv_vizio

TMP = tempfile.mkdtemp(prefix="guest-tv-vizio-")
tvbrands.DATA = TMP   # tokens go here, not in data/
CERT, KEY = os.path.join(TMP, "c.pem"), os.path.join(TMP, "k.pem")
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=standin.vizio.test",
                "-keyout", KEY, "-out", CERT], capture_output=True, check=True)
TLS = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
TLS.load_cert_chain(CERT, KEY)

PIN, TOKEN, REQ = "4821", "standin-token-9c2e", 551234
TV = {"power": 1, "app": {"NAME_SPACE": 4, "APP_ID": "1", "MESSAGE": ""}, "token": None, "wrong": 0, "busy": False,
      "readable": True, "keys": [], "launched": [], "log": [], "up": True, "bad_app": None}


def st(result):
    return {"STATUS": {"RESULT": result, "DETAIL": result}}


class VizioHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, body, code=200):
        b = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def handle_any(self):
        n = int(self.headers.get("content-length") or 0)
        text = self.rfile.read(n).decode() if n else ""
        data = json.loads(text) if text else None
        path = self.path
        TV["log"].append((self.command, path, data, self.headers.get("AUTH")))
        if not TV["up"]:
            return self.reply({}, 503)
        if path.startswith("/pairing/"):
            return self.reply(self.pairing(path, data or {}))
        if TV["token"] is None or self.headers.get("AUTH") != TV["token"]:
            return self.reply(st("requires_pairing"), 403)
        if path == "/state/device/power_mode":
            return self.reply(st("success") | {"ITEMS": [{"CNAME": "power_mode", "VALUE": TV["power"]}]})
        if path == "/key_command/":
            k = (data or {}).get("KEYLIST") or [{}]
            cs, c = k[0].get("CODESET"), k[0].get("CODE")
            TV["keys"].append((cs, c))
            return self.reply(st("success"))
        if path == "/app/current":
            if not TV["readable"]:
                return self.reply(st("uri_not_found"))
            return self.reply(st("success") | {"ITEM": {"VALUE": TV["app"]}})
        if path == "/app/launch":
            v = (data or {}).get("VALUE") or {}
            TV["launched"].append((v.get("NAME_SPACE"), v.get("APP_ID"), v.get("MESSAGE")))
            TV["app"] = {"NAME_SPACE": v.get("NAME_SPACE"), "APP_ID": v.get("APP_ID"), "MESSAGE": None}
            return self.reply(st("success"))
        return self.reply(st("uri_not_found"))

    def pairing(self, path, d):
        if path == "/pairing/start":
            if TV["busy"]:
                return st("BLOCKED")
            return st("SUCCESS") | {"ITEM": {"PAIRING_REQ_TOKEN": REQ, "CHALLENGE_TYPE": 1}}
        if path == "/pairing/pair":
            if d.get("PAIRING_REQ_TOKEN") != REQ:
                return st("CHALLENGE_INCORRECT")
            if TV["wrong"] >= 3:
                return st("MAX_CHALLENGES_EXCEEDED")
            if d.get("RESPONSE_VALUE") != PIN:
                TV["wrong"] += 1
                return st("PAIRING_DENIED")
            TV["token"] = TOKEN
            return st("SUCCESS") | {"ITEM": {"AUTH_TOKEN": TOKEN}}
        return st("uri_not_found")

    do_GET = do_PUT = do_POST = handle_any


class NotAVizio(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        b = b"<html>router</html>"
        self.send_response(403)
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def serve(handler, tls=True):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    if tls:
        srv.socket = TLS.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


PORT, DECOY = serve(VizioHandler), serve(NotAVizio)
ok = bad = 0


def check(name, cond):
    global ok, bad
    ok, bad = ok + bool(cond), bad + (not cond)
    print(("PASS " if cond else "FAIL ") + name, flush=True)


def raises(fn, word=None):
    try:
        fn()
        return False
    except Exception as e:
        return word is None or word in str(e)


def wait_for(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


# the first port answers with a web page, not SmartCast: the driver moves on to the next
tv_vizio.VizioTV.PORTS = [DECOY, PORT]
tv = tvbrands.make("vizio", "127.0.0.1")
check("make() gives the VIZIO driver", isinstance(tv, tv_vizio.VizioTV) and tv.kind == "vizio")
check("the flags: PIN pairing, no welcome screen", tv.pairing == "pin" and tv.can_open is False)

# before pairing
check("unpaired: the TV answers but not to us, so is_on is None", tv.is_on() is None)
check("the first port was not a VIZIO, the second was", tv.port == PORT)
check("unpaired: the app list says to pair", raises(tv.app_ids, "pairing"))
check("unpaired: a key says to pair", raises(lambda: tv.key("ok"), "pairing"))
check("a PIN before asking for one is refused", raises(lambda: tv.pair_finish("4821"), "PIN first"))

# pairing
TV["busy"] = True
check("a TV busy with another pairing says so", raises(tv.pair_start, "already showing a PIN"))
TV["busy"] = False
tv.pair_start()
check("the TV showed a PIN: the request is kept", "pending" in tv._stored())
check("a PIN that is not 4 digits is refused before it is sent", raises(lambda: tv.pair_finish("12ab"), "4 digits"))
check("a wrong PIN is refused in plain words", raises(lambda: tv.pair_finish("0000"), "refused the PIN"))
check("a wrong PIN clears the pairing", "pending" not in tv._stored() and tv._token() is None)
tv.pair_start()
tv.pair_finish(PIN)
check("the right PIN: the token is kept", tv._token() == TOKEN)
mode = oct(os.stat(tv.token_file).st_mode & 0o777)
check("the key file is 0600", mode == "0o600")
check("the PIN and token are not in the file's name or errors", PIN not in tv.token_file and TOKEN not in tv.token_file)
TV["wrong"] = 3
tv.pair_start()
check("too many wrong PINs says wait", raises(lambda: tv.pair_finish("1111"), "too many wrong PINs"))
TV["wrong"] = 0
tv2 = tv_vizio.VizioTV("127.0.0.1")
check("a new driver reads the kept token and device id", tv2._token() == TOKEN and tv2._device_id() == tv._device_id())

# reading
check("power 1 is on", tv.is_on() is True)
TV["power"] = 0
check("power 0 is standby", tv.is_on() is False)
TV["power"] = 1
TV["up"] = False
check("not answering is None", tv.is_on() is None)
check("not answering: the app list says so", raises(lambda: tv_vizio.VizioTV("127.0.0.1").app_ids()))
TV["up"] = True
check("VIZIO's own home is nothing", tv.front() is None and tv.nothing(tv.front()))
tv.found = (0.0, {})
ids = tv.app_ids()
check("guest apps from the fixed table", sorted(ids) == ["apple-tv", "disney-plus", "netflix", "paramount-plus", "prime-video", "youtube"])
check("no Australian app is claimed", "stan" not in ids and "binge" not in ids)
check("installed() lists tvctl apps", {a["id"] for a in tv.installed()} == set(ids))
TV["app"] = {"NAME_SPACE": 3, "APP_ID": "1", "MESSAGE": None}
check("front() names Netflix as vizio.3.1", tv.front() == "vizio.3.1" and not tv.nothing(tv.front()))
TV["app"] = {"NAME_SPACE": 4, "APP_ID": "4", "MESSAGE": None}
check("name spaces 2 and 4 are the same app (Prime Video)", tv.front() == "vizio.2.4")
TV["app"] = {"NAME_SPACE": 9, "APP_ID": "77", "MESSAGE": None}
check("an app we do not know still gives its ids", tv.front() == "vizio.9.77")
TV["readable"] = False
check("a TV that does not say what is on screen: front() is None", tv.front() is None)
TV["readable"] = True
check("guest-tv is never on screen", not tv.is_guest("vizio.3.1") and not tv.is_guest(None))

# launching and keys
tv.launch("vizio.3.1")
check("launch sends the name space and app id, message null", TV["launched"][-1] == (3, "1", None))
for bad_id in ["vizio.3.1; rm -rf /", "../../x", "netflix", "vizio.3.", "vizio.300.1", "", None, "vizio.3.\n1"]:
    TV["launched"].clear()
    check("an unsafe id is refused and never sent: %r" % (bad_id,), raises(lambda: tv.launch(bad_id)) and not TV["launched"])
tv.open_app("youtube")
check("open_app opens YouTube", TV["launched"][-1] == (5, "1", None))
check("an app not on the TV's table is refused", raises(lambda: tv.open_app("stan"), "not on this TV"))
TV["keys"].clear()
expected = {"up": (3, 8), "down": (3, 0), "left": (3, 1), "right": (3, 7), "ok": (3, 2), "back": (4, 0),
            "next": (2, 0), "previous": (2, 1), "rewind": (2, 1), "fast_forward": (2, 0)}
for name, code in expected.items():
    TV["keys"].clear()
    tv.key(name)
    check("key %s goes out as %s" % (name, code), TV["keys"] == [code])
check("every guest key name is covered", set(tvctl.KEYS) - {"home", "mute", "volume_up", "volume_down", "play_pause"} == set(expected))
TV["keys"].clear()
tv.key("play_pause")
tv.key("play_pause")
tv.key("play_pause")
check("play_pause alternates the separate play and pause keys", TV["keys"] == [(2, 3), (2, 2), (2, 3)])
TV["keys"].clear()
tv.key("volume_up", 3)
tv.key("volume_down")
check("volume goes out as volume keys", TV["keys"] == [(5, 1)] * 3 + [(5, 0)])
TV["keys"].clear()
tv.volume(True)
tv.volume(False)
check("volume(up) works directly", TV["keys"] == [(5, 1), (5, 0)])
TV["keys"].clear()
tv.key("mute")
tv.mute(True)
tv.mute(False)
check("mute: toggle, on, off", TV["keys"] == [(5, 4), (5, 3), (5, 2)])
TV["keys"].clear()
tv.key("home")
check("Home presses VIZIO's own Home, not the welcome screen", TV["keys"] == [(4, 15)])
check("a key outside the table is refused", raises(lambda: tv.key("power"), "power") and raises(lambda: tv.key("input")))
check("nothing a guest types reaches the TV: no key table entry for text", raises(lambda: tv.key("hello world")))

# links
TV["launched"].clear()
how = tv.open_link("intent://www.netflix.com/watch/80057281#Intent;scheme=https;package=com.netflix.ninja;end", "netflix")
check("a Netflix link opens the app only (no deep link on a VIZIO)", how == "app" and TV["launched"] == [(3, "1", None)])
check("open_link quietens the watcher", tv.quiet_until > time.monotonic() + 30)
how = tv.open_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube")
check("a YouTube link opens the app only", how == "app" and TV["launched"][-1] == (5, "1", None))
check("a link with no app is refused", raises(lambda: tv.open_link("https://example.com", None)))
check("Spotify is not on a VIZIO and says so", raises(lambda: tv.spotify("anything"), "not on this TV"))
check("playing() is False", tv.playing("x") is False)
check("no ADB on a VIZIO", raises(lambda: tv.sh("ls"), "no ADB"))

# the welcome screen
tv.page = "http://192.0.2.10:5410/tv/?tv=guest&brand=vizio"
TV["launched"].clear()
TV["keys"].clear()
check("open_guest_app refuses in plain words", raises(tv.open_guest_app, "cannot open on a VIZIO"))
check("it sent nothing to the TV", not TV["launched"] and not TV["keys"])

# the hook: it must do nothing at all on a VIZIO
tv.quiet_until = 0
TV["power"] = 0
stop = threading.Event()
th = threading.Thread(target=tvbrands.watch, args=(tv, 0.2, stop), daemon=True)
before = len(TV["log"])
th.start()
check("the watcher says once why it leaves a VIZIO alone", wait_for(lambda: any("cannot show" in x for x in tv.log), 2))
TV["power"] = 1
time.sleep(1.0)
check("standby to on: the hook opened nothing and sent nothing", not TV["launched"] and not TV["keys"] and len(TV["log"]) == before)
stop.set()
check("the watcher says why in the log", any("cannot show guest-tv" in x for x in tv.log))
tv.quiet()
TV["power"] = 0
th = threading.Thread(target=tvbrands.watch, args=(tv, 0.2, stop), daemon=True)
th.start()
time.sleep(0.5)
TV["power"] = 1
time.sleep(1.0)
check("a command just ran (quiet): still nothing opened", not TV["launched"])
stop.set()

# the Guest remote and the agent keep working
check("make() twice for the same address is a fresh driver each time", tvbrands.make("vizio", "127.0.0.1") is not tv)
check("the module has SETUP lines and no TV side app", isinstance(tv_vizio.SETUP, list) and not hasattr(tv_vizio, "build"))
check("a bad certificate is accepted for this TV only (context is per request)", tv._ssl().verify_mode == ssl.CERT_NONE)
src = open(os.path.join(os.path.dirname(HERE), "tv_vizio.py")).read()
check("the driver never builds a shell command", "subprocess" not in src and "os.system" not in src)
check("no real address is in the driver", not __import__("re").search(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+", src))

print("\n%d passed, %d failed" % (ok, bad))
sys.exit(1 if bad else 0)
