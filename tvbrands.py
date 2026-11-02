"""TV control for Samsung (Tizen) and LG (webOS) TVs: the same calls as tvctl.TV, so the Guest remote
and the guest agent work unchanged. Set "tv_kind": "samsung" or "lg" next to the TV's address.

Cut down from couch-tv's bridge/samsung.py and bridge/lg.py (github.com/Seagey/couch-tv) to what
guest-tv uses. Everything is on the home Wi-Fi:

- Samsung: REST on port 8001 (power, which app is on screen, opening apps, no pairing), the network
  remote on 8002 (keys; the TV asks "Allow" once, then gives a token), DIAL on 8080 (Netflix and
  YouTube titles), UPnP on 9197 (mute: a 2021 Frame ignores the remote's mute key).
- LG: the network remote (SSAP) on 3000, or 3001 encrypted (the TV asks to accept it once, then
  gives a client key), and the pointer socket it hands out for the buttons.

The tokens are kept in data/ (git ignored). Only a fixed table of keys and the guest apps go out:
nothing a guest types reaches the TV, except a show title turned into a Netflix or YouTube id.

What these TVs cannot do here: the Guest profile picker (no way to read the screen), Spotify search
(Spotify just opens), screenshots.
"""
import base64, json, os, re, socket, ssl, threading, time, urllib.error, urllib.parse, urllib.request

import tvctl

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# The guest-tv app's id on each TV (tv-apps/samsung/config.xml, tv-apps/lg/appinfo.json).
GUEST_APP = {"samsung": "GuestTVApp.Home", "lg": "app.guesttv.home"}

# Samsung and LG ids for the apps in tvctl.APPS (from couch-tv's bridge/apps.py). LG also finds apps
# by the name the TV lists them under, so most LG rows only need the name.
TIZEN = {
    "netflix": ["3201907018807", "11101200001"], "stan": ["3201606009798"],
    "disney-plus": ["3201901017640", "3202009021709", "3202204027038"],
    "prime-video": ["3201910019365", "3201512006785"], "youtube": ["111299001912"],
    "abc-iview": ["3201812017479"], "sbs-on-demand": ["3201510005981"], "binge": ["3202010022098"],
    "apple-tv": ["3201807016597"], "paramount-plus": ["3202110025305", "3201710014981"],
    "9now": ["3201607010031"], "7plus": ["3201803015934"], "10play": ["3201704012147"],
    "kayo": ["3201910019354"], "spotify": ["3201606009684"],
}
WEBOS = {"netflix": ["netflix"], "disney-plus": ["com.disney.disneyplus-prod"], "prime-video": ["amazon"],
         "youtube": ["youtube.leanback.v4"], "spotify": ["spotify-beehive"]}

SAMSUNG_KEYS = {"up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT", "ok": "KEY_ENTER",
                "back": "KEY_RETURN", "play_pause": "KEY_PLAY", "next": "KEY_FF", "previous": "KEY_REWIND",
                "rewind": "KEY_REWIND", "fast_forward": "KEY_FF", "volume_up": "KEY_VOLUP",
                "volume_down": "KEY_VOLDOWN"}
LG_KEYS = {"up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT", "ok": "ENTER", "back": "BACK",
           "play_pause": "PLAY", "next": "FASTFORWARD", "previous": "REWIND", "rewind": "REWIND",
           "fast_forward": "FASTFORWARD"}
# What an LG shows when no app is: its home, live TV, an input.
LG_NOTHING = re.compile(r"^$|^com\.webos\.app\.(home|homeconnect|launcher|livetv|hdmi\d*|externalinput\..+|inputcommon)$")
LG_OFF = {"Power Off", "Suspend", "Active Standby"}
LG_PERMISSIONS = [
    "APP_TO_APP", "CLOSE", "CONTROL_AUDIO", "CONTROL_DISPLAY", "CONTROL_INPUT_JOYSTICK",
    "CONTROL_INPUT_MEDIA_PLAYBACK", "CONTROL_INPUT_TV", "CONTROL_MOUSE_AND_KEYBOARD", "CONTROL_POWER",
    "LAUNCH", "LAUNCH_WEBAPP", "READ_APP_STATUS", "READ_INSTALLED_APPS", "READ_INPUT_DEVICE_LIST",
    "READ_NETWORK_STATE", "READ_POWER_STATE", "READ_RUNNING_APPS", "READ_TV_CURRENT_TIME",
]
DEVMODE_APP = "com.palmdts.devmode"


class TVUnavailable(RuntimeError):
    """The TV did not answer, or nobody has pressed Allow on it yet."""


def netflix_id(link):
    m = re.search(r"netflix\.com/(?:[a-z]{2}(?:-[a-z]{2})?/)?(?:title|watch)/(\d+)", link or "")
    return m.group(1) if m else None


def youtube_id(link):
    m = re.search(r"(?:[?&]v=|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})", link or "")
    return m.group(1) if m else None


def plain(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _token_file(kind, ip):
    return os.path.join(DATA, "%s-%s.key" % (kind, ip.replace(":", "_")))


def _read(path):
    try:
        return open(path).read().strip() or None
    except FileNotFoundError:
        return None


def _keep(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(str(value))
    os.chmod(path, 0o600)


def _http(method, url, body=None, headers=None, timeout=4):
    req = urllib.request.Request(url, data=body.encode() if isinstance(body, str) else body,
                                 headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


class _Base:
    kind = ""
    can_profiles = False

    def __init__(self, ip):
        self.ip = ip
        self.lock = threading.Lock()
        self.ws = None
        self.quiet_until = 0.0   # the watcher leaves the TV alone until then (a guest's command just ran)
        self.found = (0.0, {})   # (when, {app id in tvctl.APPS: the TV's id})
        self.log = []            # the watcher's last few decisions, for /api/tvs

    def note(self, what):
        self.log = (self.log + [time.strftime("%H:%M:%S ") + what])[-8:]

    def quiet(self, seconds=20):
        self.quiet_until = time.monotonic() + seconds

    # the calls tvctl.TV has
    def installed(self):
        ids = self.app_ids()
        return [a for a in tvctl.APPS if a["id"] in ids]

    def key(self, name, times=1):
        self.quiet()
        if name == "mute":
            return self.mute()
        if name in ("volume_up", "volume_down"):
            for _ in range(max(1, min(int(times), 10))):
                self.volume(name == "volume_up")
            return
        if name == "home":
            return self.open_guest_app()
        code = self.KEYS[name]   # KeyError for anything not in the table
        for _ in range(max(1, min(int(times), 10))):
            self.button(code)

    def open_app(self, app_id):
        self.quiet()
        tid = self.app_ids().get(app_id)
        if not tid:
            raise TVUnavailable("%s is not on this TV" % tvctl.BY_ID[app_id]["name"])
        self.launch(tid)

    def spotify(self, query):
        """No search by keys on these TVs: Spotify just opens and the guest picks."""
        self.open_app("spotify")
        return False

    def playing(self, package):
        return False

    def sh(self, cmd, t=20):
        raise TVUnavailable("this is a %s TV: no ADB" % self.kind)


class SamsungTV(_Base):
    kind = "samsung"
    KEYS = SAMSUNG_KEYS
    REST, WS, DIAL, UPNP = 8001, 8002, 8080, 9197   # the TV's ports (tools/brands_test.py moves them)
    COLD, BLIND = 8, [8, 3]   # Netflix on a 2021 Frame: profile screen on a cold start; the card, OK opens, OK plays

    def __init__(self, ip, name="guest-tv"):
        super().__init__(ip)
        self.name = name
        self.token_file = _token_file("samsung", ip)

    def _rest(self, method, path, timeout=3):
        return _http(method, "http://%s:%d/api/v2/%s" % (self.ip, self.REST, path), timeout=timeout)

    def is_on(self):
        """True on, False in standby, None when it does not answer (off or gone)."""
        try:
            code, body = self._rest("GET", "", timeout=2)
            if code != 200:
                return None
            dev = json.loads(body or "{}").get("device") or {}
            return (dev.get("PowerState") or "on") == "on"   # older TVs leave it out and only answer when on
        except Exception:
            return None

    def app_state(self, tid):
        try:
            code, body = self._rest("GET", "applications/" + urllib.parse.quote(tid))
            return json.loads(body) if code == 200 and body else None
        except Exception:
            return None

    def app_ids(self):
        """Which guest apps are on the TV (Samsung lists none, so it asks about each id), every 30 min."""
        at, found = self.found
        if found and time.time() - at < 1800:
            return found
        if self.is_on() is None:
            raise TVUnavailable("the TV is not answering")   # off: 25 questions would each wait 3 s
        found = {}
        for app_id, tids in TIZEN.items():
            for tid in tids:
                if (self.app_state(tid) or {}).get("id"):
                    found[app_id] = tid
                    break
        if found:
            self.found = (time.time(), found)
        return found

    def front(self):
        """The id of the app on screen: one of ours, the guest-tv app, or None (TV, HDMI, menus)."""
        for tid in [GUEST_APP["samsung"]] + list(self.app_ids().values()):
            if (self.app_state(tid) or {}).get("visible"):
                return tid
        return None

    def launch(self, tid):
        """REST opens apps on every Samsung tried; the remote's ed.apps.launch was ignored by a 2021 Frame."""
        code, body = self._rest("POST", "applications/" + urllib.parse.quote(tid), timeout=5)
        if code != 200:
            raise TVUnavailable("the TV did not open %s (%s)" % (tid, code))

    def open_guest_app(self):
        self.launch(GUEST_APP["samsung"])

    def _remote(self, wait=8):
        import websocket
        if self.ws is not None and self.ws.connected:
            return self.ws
        url = "wss://%s:%d/api/v2/channels/samsung.remote.control?name=%s" % (
            self.ip, self.WS, urllib.parse.quote(base64.b64encode(self.name.encode()).decode()))
        tok = _read(self.token_file)
        if tok:
            url += "&token=" + urllib.parse.quote(tok)
        ws = websocket.create_connection(url, timeout=wait, sslopt={"cert_reqs": ssl.CERT_NONE, "check_hostname": False})
        try:
            while True:
                j = json.loads(ws.recv())
                if j.get("event") == "ms.channel.connect":
                    new = (j.get("data") or {}).get("token")
                    if new and new != tok:
                        _keep(self.token_file, new)
                    break
                if j.get("event") == "ms.channel.unauthorized":
                    raise TVUnavailable("the TV said no to the remote: press Allow on the TV when it asks")
        except websocket.WebSocketTimeoutException:
            ws.close()
            raise TVUnavailable("the TV is waiting for someone to press Allow on its screen")
        except Exception:
            ws.close()
            raise
        ws.settimeout(5)
        self.ws = ws
        return ws

    def pair(self, wait=60):
        """The first connection: the TV shows an Allow prompt and someone presses it."""
        with self.lock:
            self.ws = None
            self._remote(wait)

    def button(self, code):
        msg = json.dumps({"method": "ms.remote.control", "params": {
            "Cmd": "Click", "DataOfCmd": code, "Option": "false", "TypeOfRemote": "SendRemoteKey"}})
        with self.lock:
            for attempt in (1, 2):
                try:
                    self._remote().send(msg)
                    break
                except TVUnavailable:
                    raise
                except Exception:
                    self.ws = None
                    if attempt == 2:
                        raise
        time.sleep(0.15)

    def volume(self, up):
        self.button("KEY_VOLUP" if up else "KEY_VOLDOWN")

    def _upnp(self, action, extra=""):
        body = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                '<u:%s xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">'
                '<InstanceID>0</InstanceID><Channel>Master</Channel>%s</u:%s></s:Body></s:Envelope>' % (action, extra, action))
        return _http("POST", "http://%s:%d/upnp/control/RenderingControl1" % (self.ip, self.UPNP), body, {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": '"urn:schemas-upnp-org:service:RenderingControl:1#%s"' % action}, timeout=3)[1]

    def muted(self):
        m = re.search(r"<CurrentMute>(\d)</CurrentMute>", self._upnp("GetMute"))
        return m and m.group(1) == "1"

    def mute(self, on=None):
        """Mute is a set over UPnP, never a toggle that can end up the wrong way round."""
        on = (not self.muted()) if on is None else on
        self._upnp("SetMute", "<DesiredMute>%d</DesiredMute>" % (1 if on else 0))

    def _dial(self, app, body):
        headers = {"Content-Type": "text/plain; charset=utf-8"}
        if app == "YouTube":
            headers["Origin"] = "https://www.youtube.com"   # without it the TV answers 403
        code, _ = _http("POST", "http://%s:%d/ws/apps/%s" % (self.ip, self.DIAL, app), body, headers, timeout=8)
        if code not in (200, 201):
            raise TVUnavailable("DIAL %s said %s" % (app, code))

    def open_link(self, uri, app_id):
        """Netflix and YouTube open the title (DIAL); every other app just opens."""
        self.quiet(40)
        nid, yid = netflix_id(uri), youtube_id(uri)
        try:
            if app_id == "netflix" and nid:
                cold = not (self.app_state(self.app_ids().get("netflix", "")) or {}).get("running")
                self._dial("Netflix", "m=https://api-global.netflix.com/catalog/titles/movies/%s&source_type=4" % nid)
                threading.Thread(target=self._press_play, args=(cold,), daemon=True).start()
                return "show"
            if app_id == "youtube" and yid:
                self._dial("YouTube", "v=" + yid)
                return "show"
        except TVUnavailable:
            pass
        self.open_app(app_id)
        return "app"

    def _press_play(self, cold):
        """Blind, timed presses: Samsung gives no way to read the screen. A cold start shows "Who's
        watching?" first, and OK takes the highlighted profile."""
        try:
            if cold:
                time.sleep(self.COLD)
                self.button("KEY_ENTER")
            for wait in self.BLIND:
                time.sleep(wait)
                self.button("KEY_ENTER")
        except Exception:
            pass


class LGTV(_Base):
    kind = "lg"
    KEYS = LG_KEYS
    PORTS = (3000, 3001)   # plain, encrypted (tools/brands_test.py moves them)

    def __init__(self, ip):
        super().__init__(ip)
        self.key_file = _token_file("lg", ip)
        self.pointer = None
        self.n = 0
        self.points = []
        self.devmode_file = os.path.join(DATA, "lg-%s-devmode.json" % ip.replace(":", "_"))

    def _connect(self, wait=8):
        import websocket
        if self.ws is not None and self.ws.connected:
            return self.ws
        last, ws = None, None
        for url in ("ws://%s:%d" % (self.ip, self.PORTS[0]), "wss://%s:%d" % (self.ip, self.PORTS[1])):   # newer firmware: encrypted only
            try:
                socket.create_connection((self.ip, int(url.rsplit(":", 1)[1])), 1.5).close()   # quick: is it there?
            except OSError as e:
                last = e
                continue
            try:
                ws = websocket.create_connection(url, timeout=5, sslopt={"cert_reqs": ssl.CERT_NONE, "check_hostname": False})
                break
            except Exception as e:
                last, ws = e, None
        if ws is None:
            raise TVUnavailable("the TV's remote port did not open (%s)" % type(last).__name__)
        try:
            self._register(ws, wait)
        except Exception:
            ws.close()
            raise
        self.ws, self.pointer, self.url = ws, None, url
        return ws

    def _register(self, ws, wait):
        import websocket
        ws.send(json.dumps({"id": "hello", "type": "hello", "payload": {}}))
        ws.recv()
        key = _read(self.key_file)
        payload = {"forcePairing": False, "pairingType": "PROMPT",
                   "manifest": {"appVersion": "1.1", "manifestVersion": 1, "permissions": LG_PERMISSIONS}}
        if key:
            payload["client-key"] = key
        ws.send(json.dumps({"id": "register_0", "type": "register", "payload": payload}))
        end, prompting = time.monotonic() + 8, False
        while True:
            ws.settimeout(max(0.1, end - time.monotonic()))
            try:
                j = json.loads(ws.recv())
            except websocket.WebSocketTimeoutException:
                raise TVUnavailable("the TV is waiting for someone to accept the remote on its screen" if prompting
                                    else "the TV did not answer the remote's hello")
            if j.get("id") != "register_0":
                continue
            if j.get("type") == "response" and (j.get("payload") or {}).get("pairingType") == "PROMPT":
                prompting, end = True, time.monotonic() + wait
            elif j.get("type") == "registered":
                new = (j.get("payload") or {}).get("client-key")
                if new and new != key:
                    _keep(self.key_file, new)
                ws.settimeout(6)
                return
            elif j.get("type") == "error":
                raise TVUnavailable("the TV said no to the remote (%s): accept it on the TV when it asks" % j.get("error"))

    def pair(self, wait=60):
        with self.lock:
            self.ws = None
            self._connect(wait)

    def request(self, uri, payload=None):
        with self.lock:
            for attempt in (1, 2):
                try:
                    ws = self._connect()
                    self.n += 1
                    rid = "g%d" % self.n
                    ws.send(json.dumps({"id": rid, "type": "request", "uri": "ssap://" + uri, "payload": payload or {}}))
                    while True:
                        j = json.loads(ws.recv())
                        if j.get("id") == rid:
                            break
                    break
                except TVUnavailable:
                    raise
                except Exception:
                    self.ws = None
                    if attempt == 2:
                        raise TVUnavailable("the TV did not answer " + uri)
        if j.get("type") == "error":
            raise TVUnavailable("%s: %s" % (uri, j.get("error")))
        p = j.get("payload") or {}
        if p.get("returnValue") is False:
            raise TVUnavailable("%s: %s" % (uri, p.get("errorText") or "failed"))
        return p

    def is_on(self):
        try:
            state = self.request("com.webos.service.tvpower/power/getPowerState").get("state")
            return state not in LG_OFF
        except TVUnavailable as e:
            if "404" in str(e) or "no such service" in str(e).lower():
                return True   # older webOS has no power service and only answers when on
            return None
        except Exception:
            return None

    def app_ids(self):
        """The guest apps on the TV, by LG's id or by the name it lists them under, every 30 min."""
        at, found = self.found
        if found and time.time() - at < 1800:
            return found
        points = self.request("com.webos.applicationManager/listLaunchPoints").get("launchPoints") or []
        self.points = points
        names = {plain(a["name"]): a["id"] for a in tvctl.APPS}
        found = {}
        for lp in points:
            lid = lp.get("id") or ""
            aid = next((k for k, ids in WEBOS.items() if lid in ids), None) or names.get(plain(lp.get("title")))
            if aid and aid not in found:
                found[aid] = lid
        if found:
            self.found = (time.time(), found)
        return found

    def front(self):
        try:
            return self.request("com.webos.applicationManager/getForegroundAppInfo").get("appId") or None
        except TVUnavailable:
            return None

    def launch(self, lid, content_id=None, params=None):
        p = {"id": lid}
        if content_id:
            p["contentId"] = content_id
        if params:
            p["params"] = params
        self.request("system.launcher/launch", p)

    def open_guest_app(self):
        self.launch(GUEST_APP["lg"])

    def button(self, name):
        import websocket
        for attempt in (1, 2):
            try:
                if self.pointer is None or not self.pointer.connected:
                    path = self.request("com.webos.service.networkinput/getPointerInputSocket").get("socketPath")
                    if not path:
                        raise TVUnavailable("the TV did not give a pointer socket")
                    tries = [path]
                    if path.startswith("ws://") and getattr(self, "url", "").startswith("wss://"):
                        tries.append("wss://" + path[5:].replace(":%d/" % self.PORTS[0], ":%d/" % self.PORTS[1], 1))
                    for url in tries:
                        try:
                            self.pointer = websocket.create_connection(url, timeout=5, sslopt={"cert_reqs": ssl.CERT_NONE, "check_hostname": False})
                            break
                        except Exception:
                            self.pointer = None
                    if self.pointer is None:
                        raise TVUnavailable("the TV's pointer socket did not open")
                self.pointer.send("type:button\nname:%s\n\n" % name)
                time.sleep(0.15)
                return
            except TVUnavailable:
                raise
            except Exception:
                self.pointer = None
                if attempt == 2:
                    raise

    def volume(self, up):
        self.request("audio/volumeUp" if up else "audio/volumeDown")

    def mute(self, on=None):
        if on is None:
            p = self.request("audio/getVolume")
            v = p.get("volumeStatus") or p
            on = not bool(v.get("muteStatus", v.get("muted")))
        self.request("audio/setMute", {"mute": bool(on)})

    def open_link(self, uri, app_id):
        """Netflix and YouTube open the title (as LG's own integrations do); every other app just opens."""
        self.quiet(40)
        nid, yid = netflix_id(uri), youtube_id(uri)
        lid = self.app_ids().get(app_id)
        if lid and app_id == "netflix" and nid:
            self.launch(lid, content_id="m=https://api-global.netflix.com/catalog/titles/movies/%s&source_type=4" % nid)
            return "show"
        if lid and app_id == "youtube" and yid:
            self.launch(lid, params={"contentTarget": "https://www.youtube.com/tv?v=" + yid})
            return "show"
        self.open_app(app_id)
        return "app"

    def extend_devmode(self):
        """LG removes Developer Mode apps when the session runs out (about 50 hours). Once a day this
        presses Developer Mode's Extend: LG's ares-launch when it is installed, else the same setting
        over the network remote (as couch-tv does; the second way is not proven on a real LG)."""
        import shutil, subprocess
        state = {"date": time.strftime("%Y-%m-%d"), "ok": False}
        ares = shutil.which("ares-launch")
        try:
            if ares:
                state["how"] = "ares-launch"
                r = subprocess.run([ares, "--device", os.environ.get("ARES_DEVICE", "tv"), DEVMODE_APP, "-p",
                                    json.dumps({"extend": True})], capture_output=True, text=True, timeout=60)
                state["ok"] = r.returncode == 0
            else:
                state["how"] = "remote"
                self.launch(DEVMODE_APP, params={"extend": True})
                state["ok"] = True
        except Exception as e:
            state["error"] = str(e)[:200]
        _keep(self.devmode_file, json.dumps(state))
        self.note("Developer Mode extend %s (%s)" % ("done" if state["ok"] else "failed", state.get("how")))
        return state["ok"]

    def devmode_due(self):
        try:
            return json.load(open(self.devmode_file)).get("date") != time.strftime("%Y-%m-%d")
        except (FileNotFoundError, ValueError):
            return True


def nothing_on_screen(tv, front):
    if tv.kind == "lg":
        return front is None or bool(LG_NOTHING.match(front))
    return front is None


def watch(tv, every=2.0, stop=None):
    """The hook. Each time the TV comes on and nothing else is on screen, open the guest-tv app, so
    the TV "looks for" guest-tv every time it is switched on. It leaves the TV alone when an app is on
    screen, and for 20 seconds after a guest's own command. Runs until stop is set."""
    was_on = None
    while not (stop and stop.is_set()):
        try:
            on = tv.is_on()
            if on and was_on is not True:
                time.sleep(1.5)   # let the TV settle on whatever it opens by itself
                front = tv.front()
                if time.monotonic() < tv.quiet_until:
                    tv.note("TV came on, left alone (a guest command is running)")
                elif front == GUEST_APP[tv.kind]:
                    tv.note("TV came on, guest-tv already open")
                elif not nothing_on_screen(tv, front):
                    tv.note("TV came on in %s, left alone" % front)
                else:
                    if tv.kind == "lg" and tv.devmode_due():
                        tv.extend_devmode()
                        time.sleep(2)
                    tv.open_guest_app()
                    tv.note("TV came on, opened guest-tv")
            elif on and tv.kind == "lg" and tv.devmode_due() and time.monotonic() >= tv.quiet_until:
                front = tv.front()   # a TV left on for days: extend while guest-tv or live TV is up
                if front == GUEST_APP["lg"] or nothing_on_screen(tv, front):
                    tv.extend_devmode()
                    time.sleep(2)
                    if front == GUEST_APP["lg"]:
                        tv.open_guest_app()
            was_on = bool(on)   # no answer counts as off
        except Exception as e:
            tv.note("watch: %s %s" % (type(e).__name__, str(e)[:80]))
            was_on = False if was_on is None else was_on
        time.sleep(every)
