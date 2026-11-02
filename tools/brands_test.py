"""Test the Samsung and LG TV control (tvbrands.py), the hook and the TV page's routes, with no real
TV and no Claude. A stand-in Samsung and a stand-in LG run on this computer for the test, answering
the way couch-tv's notes and LG's documentation say the real ones do.

    .venv/bin/python tools/brands_test.py      (needs: pip install websockets)
"""
import asyncio, base64, logging, json, os, ssl, subprocess, sys, tempfile, threading, time, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import tvbrands, tvctl

logging.getLogger("websockets").setLevel(logging.CRITICAL)
TMP = tempfile.mkdtemp(prefix="guest-tv-brands-")
tvbrands.DATA = TMP   # tokens go here, not in data/
CERT, KEY = os.path.join(TMP, "c.pem"), os.path.join(TMP, "k.pem")
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=tv",
                "-keyout", KEY, "-out", CERT], capture_output=True, check=True)
TLS = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
TLS.load_cert_chain(CERT, KEY)
loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()


def run(coro):
    return asyncio.run_coroutine_threadsafe(coro, loop).result(10)


def http(port, handler):
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, body=""):
        b = (json.dumps(body) if isinstance(body, (dict, list)) else body).encode()
        self.send_response(code)
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        return self.rfile.read(int(self.headers.get("content-length") or 0)).decode()


# ---------------------------------------------------------------- stand-in Samsung
SAM = {"power": "on", "up": True, "apps": {"3201907018807": "Netflix", "111299001912": "YouTube",
       "3201606009798": "Stan", "GuestTVApp.Home": "Guest TV"}, "visible": None, "running": set(),
       "keys": [], "dial": [], "muted": False, "token": "tok-123", "allow": True, "launched": []}


class SamRest(Handler):
    def do_GET(self):
        if not SAM["up"]:
            return self.reply(503)
        if self.path == "/api/v2/":
            return self.reply(200, {"device": {"PowerState": SAM["power"], "FrameTVSupport": "true"}})
        tid = urllib.parse.unquote(self.path.rsplit("/", 1)[1])
        if tid not in SAM["apps"]:
            return self.reply(404, {"message": "not found"})
        self.reply(200, {"id": tid, "name": SAM["apps"][tid], "running": tid in SAM["running"],
                         "visible": SAM["visible"] == tid})

    def do_POST(self):
        tid = urllib.parse.unquote(self.path.rsplit("/", 1)[1])
        if tid not in SAM["apps"]:
            return self.reply(404, {"message": "not found"})
        SAM["visible"] = tid
        SAM["running"].add(tid)
        SAM["launched"].append(tid)
        self.reply(200, "true")


class SamDial(Handler):
    def do_POST(self):
        app = self.path.rsplit("/", 1)[1]
        if app == "YouTube" and self.headers.get("Origin") != "https://www.youtube.com":
            return self.reply(403)
        SAM["dial"].append((app, self.body()))
        SAM["visible"] = {"Netflix": "3201907018807", "YouTube": "111299001912"}[app]
        self.reply(201)


class SamUpnp(Handler):
    def do_POST(self):
        act = self.headers.get("SOAPACTION", "").split("#")[1].strip('"')
        b = self.body()
        if act == "SetMute":
            SAM["muted"] = "<DesiredMute>1</DesiredMute>" in b
            return self.reply(200, "<ok/>")
        self.reply(200, "<CurrentMute>%d</CurrentMute>" % SAM["muted"])


async def sam_remote(ws):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(ws.request.path).query)
    if base64.b64decode(q["name"][0]).decode() != "guest-tv":
        await ws.close()
        return
    if q.get("token", [""])[0] != SAM["token"]:
        await asyncio.sleep(0.3)   # the Allow prompt
        if not SAM["allow"]:
            await ws.send(json.dumps({"event": "ms.channel.unauthorized"}))
            return
    await ws.send(json.dumps({"event": "ms.channel.connect", "data": {"token": SAM["token"]}}))
    try:
        async for m in ws:
            SAM["keys"].append(json.loads(m)["params"]["DataOfCmd"])
    except Exception:
        pass   # the remote dropped the connection to reconnect


# ---------------------------------------------------------------- stand-in LG
LG = {"power": "Active", "front": "com.webos.app.livetv", "key": "lg-key-9", "accept": True, "prompts": 0,
      "points": [{"id": "netflix", "title": "Netflix"}, {"id": "youtube.leanback.v4", "title": "YouTube"},
                 {"id": "au.stan.webos", "title": "Stan"}, {"id": "app.guesttv.home", "title": "Guest TV"}],
      "calls": [], "buttons": [], "muted": False, "plain": True}


async def lg_remote(ws):
    if ws.request.path.startswith("/pointer"):
        async for m in ws:
            LG["buttons"].append(m.split("name:")[1].strip())
        return
    async for m in ws:
        j = json.loads(m)
        if j["type"] == "hello":
            await ws.send(json.dumps({"type": "hello", "id": "hello", "payload": {}}))
        elif j["type"] == "register":
            if j["payload"].get("client-key") != LG["key"]:
                LG["prompts"] += 1
                await ws.send(json.dumps({"type": "response", "id": "register_0", "payload": {"pairingType": "PROMPT"}}))
                await asyncio.sleep(0.3)
                if not LG["accept"]:
                    await ws.send(json.dumps({"type": "error", "id": "register_0", "error": "403 cancelled"}))
                    continue
            await ws.send(json.dumps({"type": "registered", "id": "register_0", "payload": {"client-key": LG["key"]}}))
        else:
            uri, p = j["uri"][len("ssap://"):], j.get("payload") or {}
            LG["calls"].append((uri, p))
            out = {"returnValue": True}
            if uri == "com.webos.service.tvpower/power/getPowerState":
                out["state"] = LG["power"]
            elif uri == "com.webos.applicationManager/getForegroundAppInfo":
                out["appId"] = LG["front"]
            elif uri == "com.webos.applicationManager/listLaunchPoints":
                out["launchPoints"] = LG["points"]
            elif uri == "system.launcher/launch":
                LG["front"] = p["id"]
            elif uri == "com.webos.service.networkinput/getPointerInputSocket":
                port = LG_PORTS[0] if LG["plain"] else LG_PORTS[1]
                out["socketPath"] = "%s://127.0.0.1:%d/pointer/1" % ("ws" if LG["plain"] else "wss", port)
            elif uri == "audio/getVolume":
                out["volumeStatus"] = {"volume": 5, "muteStatus": LG["muted"]}
            elif uri == "audio/setMute":
                LG["muted"] = p["mute"]
            await ws.send(json.dumps({"type": "response", "id": j["id"], "payload": out}))


# ---------------------------------------------------------------- run them
from websockets.asyncio.server import serve as _serve


async def serve(*a, **k):
    return await _serve(*a, **k)


SAM_PORTS = (18001, 18002, 18080, 19197)
LG_PORTS = (13000, 13001)
http(SAM_PORTS[0], SamRest)
http(SAM_PORTS[2], SamDial)
http(SAM_PORTS[3], SamUpnp)
run(serve(sam_remote, "127.0.0.1", SAM_PORTS[1], ssl=TLS))
lg_plain = run(serve(lg_remote, "127.0.0.1", LG_PORTS[0]))
tvbrands.SamsungTV.REST, tvbrands.SamsungTV.WS, tvbrands.SamsungTV.DIAL, tvbrands.SamsungTV.UPNP = SAM_PORTS
tvbrands.SamsungTV.COLD, tvbrands.SamsungTV.BLIND = 0.2, [0.2, 0.2]
tvbrands.LGTV.PORTS = LG_PORTS

ok = bad = 0


def check(name, cond):
    global ok, bad
    ok, bad = ok + bool(cond), bad + (not cond)
    print(("PASS " if cond else "FAIL ") + name, flush=True)


def raises(fn):
    try:
        fn()
        return False
    except Exception:
        return True


def wait_for(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def hook(tv):
    """One switch-on: off, then on, with the watcher running; returns what it did."""
    stop = threading.Event()
    t = threading.Thread(target=tvbrands.watch, args=(tv, 0.2, stop), daemon=True)
    t.start()
    time.sleep(0.5)
    return stop


# ---------------------------------------------------------------- Samsung
print("Samsung")
sam = tvbrands.SamsungTV("127.0.0.1")
check("power on is on", sam.is_on() is True)
SAM["power"] = "standby"
check("standby is off", sam.is_on() is False)
SAM["up"] = False
check("not answering is None", sam.is_on() is None)
check("not answering: the app list says the TV is off, quickly", raises(sam.installed))
SAM["up"], SAM["power"] = True, "on"
check("guest apps found by their Samsung ids", [a["id"] for a in sam.installed()] == ["netflix", "stan", "youtube"])
SAM["allow"] = False
check("a No on the TV is reported", raises(lambda: sam.pair(2)))
SAM["allow"] = True
sam.pair(2)
check("Allow pressed: the token is kept", open(sam.token_file).read() == "tok-123")
sam.ws = None
sam.key("left")
sam.key("ok")
sam.key("back")
sam.key("volume_up", 3)
check("keys go out as Samsung keys", wait_for(lambda: SAM["keys"] == ["KEY_LEFT", "KEY_ENTER", "KEY_RETURN", "KEY_VOLUP", "KEY_VOLUP", "KEY_VOLUP"]))
check("a key outside the table is refused", raises(lambda: sam.key("power")))
sam.key("mute")
check("mute is set over UPnP", SAM["muted"] is True)
sam.key("mute")
check("mute again unmutes", SAM["muted"] is False)
sam.open_app("stan")
check("open Stan through REST", SAM["visible"] == "3201606009798")
check("an app not on the TV is refused", raises(lambda: sam.open_app("kayo")))
SAM["keys"].clear()
how = sam.open_link("intent://www.netflix.com/watch/80057281#Intent;scheme=https;package=com.netflix.ninja;end", "netflix")
check("Netflix title through DIAL", how == "show" and "80057281" in SAM["dial"][-1][1])
check("cold Netflix: OK for the profile, then OK twice", wait_for(lambda: SAM["keys"] == ["KEY_ENTER"] * 3))
how = sam.open_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube")
check("YouTube video through DIAL", how == "show" and SAM["dial"][-1] == ("YouTube", "v=dQw4w9WgXcQ"))
how = sam.open_link("intent://www.stan.com.au/watch/123#Intent;end", "stan")
check("Stan link: Stan opens", how == "app" and SAM["visible"] == "3201606009798")
check("front() names the app on screen", sam.front() == "3201606009798")

# the hook
sam.quiet_until = 0
SAM["power"], SAM["visible"], SAM["launched"] = "standby", None, []
stop = hook(sam)
SAM["power"] = "on"
check("TV comes on to nothing: guest-tv opens", wait_for(lambda: SAM["launched"] == ["GuestTVApp.Home"]))
SAM["power"] = "standby"
time.sleep(0.5)
SAM["visible"], SAM["power"] = "3201907018807", "on"
time.sleep(2.5)
check("TV comes on in Netflix: left alone", SAM["launched"] == ["GuestTVApp.Home"])
SAM["power"] = "standby"
time.sleep(0.5)
SAM["visible"] = None
sam.quiet()
SAM["power"] = "on"
time.sleep(2.5)
check("a guest command just ran: left alone", SAM["launched"] == ["GuestTVApp.Home"])
SAM["up"] = False
time.sleep(0.6)
sam.quiet_until = 0
SAM["up"], SAM["visible"] = True, None
check("back on the network after being off: guest-tv opens", wait_for(lambda: SAM["launched"][-1:] == ["GuestTVApp.Home"] and len(SAM["launched"]) == 2, 4))
stop.set()
check("the watcher wrote down what it did", any("opened guest-tv" in x for x in sam.log))

# ---------------------------------------------------------------- LG
print("LG")
lg = tvbrands.LGTV("127.0.0.1")
LG["accept"] = False
check("a No on the TV is reported", raises(lambda: lg.pair(2)))
LG["accept"] = True
lg.pair(2)
check("accepted: the client key is kept", open(lg.key_file).read() == "lg-key-9")
lg.ws = None
before = LG["prompts"]
check("power Active is on", lg.is_on() is True)
check("the kept key: no second prompt", LG["prompts"] == before)
LG["power"] = "Active Standby"
check("Active Standby is off", lg.is_on() is False)
LG["power"] = "Active"
check("guest apps found by name", sorted(a["id"] for a in lg.installed()) == ["netflix", "stan", "youtube"])
lg.key("left")
lg.key("ok")
lg.key("back")
check("buttons go over the pointer socket", wait_for(lambda: LG["buttons"] == ["LEFT", "ENTER", "BACK"]))
lg.key("volume_up", 2)
check("volume over SSAP", [c for c, _ in LG["calls"]].count("audio/volumeUp") == 2)
lg.key("mute")
check("mute set over SSAP", LG["muted"] is True)
lg.open_app("stan")
check("open Stan by the id the TV listed", LG["front"] == "au.stan.webos")
lg.open_link("intent://www.netflix.com/watch/80057281#Intent;end", "netflix")
check("Netflix title with contentId", LG["calls"][-1] == ("system.launcher/launch", {"id": "netflix",
      "contentId": "m=https://api-global.netflix.com/catalog/titles/movies/80057281&source_type=4"}))
lg.open_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube")
check("YouTube video with contentTarget", LG["calls"][-1][1].get("params") == {"contentTarget": "https://www.youtube.com/tv?v=dQw4w9WgXcQ"})

lg.quiet_until = 0
LG["power"], LG["front"], LG["calls"] = "Active Standby", "com.webos.app.livetv", []
stop = hook(lg)
LG["power"] = "Active"
launched = lambda: [p["id"] for c, p in LG["calls"] if c == "system.launcher/launch"]
check("TV comes on to live TV: Developer Mode extended, then guest-tv opens",
      wait_for(lambda: launched() == ["com.palmdts.devmode", "app.guesttv.home"], 6))
check("Extend asked for with extend: true", [p for c, p in LG["calls"] if c == "system.launcher/launch"][0].get("params") == {"extend": True})
LG["power"] = "Active Standby"
time.sleep(0.5)
LG["front"], LG["power"] = "netflix", "Active"
time.sleep(2.5)
check("TV comes on in Netflix: left alone, Extend not repeated the same day", launched() == ["com.palmdts.devmode", "app.guesttv.home"])
stop.set()

# encrypted port only (newer firmware)
for w in (lg.ws, lg.pointer):   # hang up first, so the stand-in can close at once
    w and w.close()
lg_plain.close()
asyncio.run_coroutine_threadsafe(lg_plain.wait_closed(), loop).result(20)
run(serve(lg_remote, "127.0.0.1", LG_PORTS[1], ssl=TLS))
LG["plain"] = False
lg2 = tvbrands.LGTV("127.0.0.1")
check("plain port closed: the encrypted one is used", lg2.is_on() is True and lg2.url.startswith("wss://"))
LG["buttons"].clear()
lg2.key("right")
check("buttons over the encrypted pointer socket", wait_for(lambda: LG["buttons"] == ["RIGHT"]))

# ---------------------------------------------------------------- the server's routes, on the stand-in Samsung
print("server")
os.environ["GUEST_TV_KIND"], os.environ["GUEST_TV_IP"] = "samsung", "127.0.0.1"
import server
server.start_tv_watchers = lambda: None
srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % srv.server_address[1]
tvctl._tvs[("samsung", "127.0.0.1")] = sam
SAM["power"], SAM["up"] = "on", True
sam.found = (0, {})


def get(path):
    with urllib.request.urlopen(base + path, timeout=30) as r:
        return r.headers, json.loads(r.read())


def post(path, body):
    req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


hid = server.home_ids()[0]
h, body = get("/api/health")
check("health answers the TV app from its own origin (CORS)", h.get("Access-Control-Allow-Origin") == "*")
allow = server.load_home(hid).get("guest_apps") or server.settings().get("guest_apps")
want = sorted(a for a in ("netflix", "stan", "youtube") if not allow or a in allow)
_, body = get("/api/tv/apps?home=" + hid)
check("the TV page's app row comes from the TV", sorted(a["id"] for a in body["apps"]) == want)
SAM["visible"] = None
r = post("/api/tv/app?home=" + hid, {"app": want[0]})
check("a tile opens its app through the computer", r.get("ok") and SAM["visible"] == tvbrands.TIZEN[want[0]][0])
r = post("/api/tv/app?home=" + hid, {"app": "kayo"})
check("an app that is not a guest app is refused", r.get("ok") is False)
code = server.remote_code(server.load_home(hid))
SAM["keys"].clear()
r = post("/api/r/key?home=%s&c=%s" % (hid, code), {"key": "down"})
check("the Guest remote's keys reach the Samsung", r.get("ok") and wait_for(lambda: SAM["keys"] == ["KEY_DOWN"]))
srv.shutdown()

print("\n%d passed, %d failed" % (ok, bad))
sys.exit(1 if bad else 0)
