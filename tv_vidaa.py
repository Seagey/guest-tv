"""Hisense VIDAA TVs for guest-tv (tv_kind "vidaa"): the same calls as tvctl.TV, so the Guest remote and
the guest agent work unchanged. Cut down from couch-tv's bridge/vidaa.py (github.com/Seagey/couch-tv),
which keeps the same honesty.

NEW (BETA). Checked against a stand-in TV on the computer only (tools/vidaa_test.py). Hisense
publishes nothing about how its TVs talk to a phone remote, so parts of this are our best reading of
it, not confirmed facts. Expect the first owner with a real VIDAA TV to find something to fix.

How a VIDAA TV is reached: an MQTT broker on the TV, over TLS, on port 36669 (36668 on older builds),
the way Hisense's own phone app talks to it (tinymqtt.py is our own small client, written from the MQTT
3.1.1 standard). Newer firmware (2024 on) wants a client certificate in the TLS handshake. guest-tv
never ships that certificate: the owner takes it from their own copy of Hisense's app and puts it in
data/vidaa/ (client.pem and client.key, see docs/VIDAA.md). It is never printed or logged.

Topics, as far as they are known. <client> is guest-tv's client id (kept in data/).

  /remoteapp/tv/ui_service/<client>/actions/vidaa_app_connect     pairing: the TV shows a 4 digit PIN
  /remoteapp/tv/ui_service/<client>/actions/authenticationcode    pairing: the PIN goes back
  /remoteapp/tv/platform_service/<client>/data/gettoken           pairing: a token is given out
  /remoteapp/tv/ui_service/<client>/actions/launchapp             open an app: appId, name, url, urlType, storeType
  /remoteapp/tv/ui_service/<client>/actions/applist               the installed apps, same fields
  /remoteapp/tv/ui_service/<client>/actions/uievent               {"type": "app_install", ...}: a tile
  /remoteapp/mobile/<client>/ui_service/data/state                where the TV is ("statetype")
  /remoteapp/mobile/broadcast/ui_service/state                    the same, sent to every client

UNCONFIRMED on a real TV, all in PROTOCOL and KEYS below: the name of the request that asks for the
state (gettvstate), that answers come back on /remoteapp/mobile/<client>/<service>/data/<name>, the
service that takes keys (remote_service) and the key names, the field the PIN travels in, the field
the token comes back in, and that the token is the MQTT password on later connections.

What guest-tv does with it: its page opens in the TV's browser, or as a tile where the firmware still
accepts one. Not a true home screen: the remote's Home button still opens VIDAA's home. No root, ever.
What it cannot do: say which app is in front (only where the TV is: home, live TV, an input, standby,
and the last app guest-tv opened), a volume level, typing, screenshots, deep links into a show, the
Guest profile picker, Spotify search (Spotify just opens).

The driver is sync like the rest of guest-tv; the MQTT client is asyncio, so it runs on a private event
loop in a daemon thread inside this file.
"""
import asyncio, json, logging, os, re, secrets, ssl, threading, time

import tvbrands, tvctl
from tvbrands import TVUnavailable, _Base, _keep, _read, _token_file, plain
from tinymqtt import Client, MQTTError, Refused

log = logging.getLogger("tv_vidaa")

TILE_ID = "app.guesttv.home"    # the id guest-tv's own tile is added under
TILE_TITLE = "Guest TV"
GUEST_FRONT = "guest-tv"        # what front() says while guest-tv is the app the TV was last asked to open

# Every topic and payload shape in one place, so a tester's trace can correct them here.
PROTOCOL = {
    "action": "/remoteapp/tv/{service}/{client}/actions/{name}",
    "token": "/remoteapp/tv/platform_service/{client}/data/gettoken",
    "listen": ["/remoteapp/mobile/{client}/#", "/remoteapp/mobile/broadcast/#"],
    "state_request": ("ui_service", "gettvstate"),     # UNCONFIRMED name
    "key_service": "remote_service",                   # UNCONFIRMED
    "pin_field": "authNum",                            # UNCONFIRMED
    "token_fields": ("accesstoken", "access_token", "token"),   # UNCONFIRMED: the first one present wins
}

# statetype values: the home, live TV, an input, a settings menu, standby, waking.
OFF_STATES = {"fake_sleep_0", "fake_sleep_1"}
NOTHING = re.compile(r"^(remote_launcher|livetv|sourceswitch)$")   # nothing of anyone's is on screen

# guest-tv's key names (tvctl.KEYS) -> VIDAA key names. UNCONFIRMED on a real TV. Home is not here:
# guest-tv's Home is its own page (open_guest_app); VIDAA's own home stays on the TV's remote.
KEYS = {
    "up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT", "ok": "KEY_OK",
    "back": "KEY_RETURNS", "play_pause": "KEY_PLAY", "next": "KEY_FORWARDS", "previous": "KEY_BACK",
    "rewind": "KEY_BACK", "fast_forward": "KEY_FORWARDS",
    "volume_up": "KEY_VOLUMEUP", "volume_down": "KEY_VOLUMEDOWN", "mute": "KEY_MUTE",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")       # an app id the TV listed, before it is sent back
SAFE_CLIENT = re.compile(r"^[A-Za-z0-9._$-]{4,64}$")   # no MQTT wildcards or slashes in a topic level
PIN = re.compile(r"^\d{4}$")
BROWSER_NAMES = ("browser", "webbrowser", "internet", "web")

# Extra names a VIDAA TV may list the guest apps under (plain() drops case, spaces and punctuation).
ALIASES = {"disney-plus": ["Disney Plus"], "prime-video": ["Amazon Prime Video", "Prime"],
           "abc-iview": ["iview", "ABC iview"], "sbs-on-demand": ["SBS", "SBS On Demand"],
           "apple-tv": ["Apple TV+", "AppleTV"], "paramount-plus": ["Paramount Plus"],
           "9now": ["9Now", "Nine Now"], "7plus": ["7plus", "7 plus"], "10play": ["10 play", "10Play"]}
BY_NAME = {}
for _a in tvctl.APPS:
    for _n in [_a["name"]] + ALIASES.get(_a["id"], []):
        BY_NAME.setdefault(plain(_n), _a["id"])


class VidaaTV(_Base):
    kind = "vidaa"
    KEYS = KEYS
    pairing = "pin"
    sees_front = True       # where the TV is, plus the last app guest-tv opened (not a true read)
    GONE_IS_OFF = 10        # a short Wi-Fi dropout is not a switch off
    SETTLE = 2.0
    PORTS = (36669, 36668)  # (tools/vidaa_test.py moves them)
    TLS = True
    RETRY_WAIT = 5          # seconds before another try after no answer
    REFUSED_WAIT = 30       # seconds before another try after the TV refused the login
    CONNECT_TIMEOUT = 3

    def __init__(self, ip):
        super().__init__(ip)
        self.store = _token_file("vidaa", ip)   # JSON: {"client_id": ..., "token": ...}, 0600
        self.cert_dir = os.path.join(tvbrands.DATA, "vidaa")
        stored = self._stored()
        cid = str(stored.get("client_id") or "")
        self.client_id = cid if SAFE_CLIENT.match(cid) else "guesttv-" + secrets.token_hex(6)
        self.statetype = None
        self.applist = []         # [{"appId", "name", "url", "urlType", "storeType"}] as the TV listed them
        self.last_error = None    # why the last connection or pairing failed, in plain words
        self.pin_shown_at = 0.0
        self._front = (None, 0.0)   # (what, when) the last app guest-tv opened
        self._mqtt = None
        self._retry_at = 0.0
        self._waiters = {}
        self._loop = None
        self._start = threading.Lock()

    # ---------- what is kept for this TV (data/, git ignored, never printed) ----------
    def _stored(self):
        try:
            d = json.loads(_read(self.store) or "{}")
            return d if isinstance(d, dict) else {}
        except ValueError:
            return {}

    def _keep(self, **changes):
        _keep(self.store, json.dumps(self._stored() | {"client_id": self.client_id} | changes))

    @property
    def token(self):
        t = self._stored().get("token")
        return t if isinstance(t, str) and t else None

    def _certs(self):
        cert, key = os.path.join(self.cert_dir, "client.pem"), os.path.join(self.cert_dir, "client.key")
        return (cert, key) if os.path.isfile(cert) and os.path.isfile(key) else None

    def status(self):
        """For tools/tv_app.py status: what a first tester needs to see. No secrets."""
        return {"connected": bool(self._mqtt and self._mqtt.alive), "statetype": self.statetype,
                "token": bool(self.token), "certificate": bool(self._certs()), "error": self.last_error}

    # ---------- the private event loop ----------
    def _run(self, coro, timeout=20):
        with self._start:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                threading.Thread(target=self._loop.run_forever, daemon=True, name="vidaa-" + self.ip).start()
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout)
        except TimeoutError:
            fut.cancel()
            raise TVUnavailable("the TV did not answer in time") from None
        except asyncio.TimeoutError:
            raise TVUnavailable("the TV did not answer in time") from None

    # ---------- the connection ----------
    def _ssl(self):
        """TLS to the TV. The TV's certificate is its own, so it is not checked against anything; the
        client certificate goes in when the owner has put one in data/vidaa/."""
        if not self.TLS:
            return None
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        pair = self._certs()
        if pair:
            try:
                ctx.load_cert_chain(*pair)
            except (ssl.SSLError, OSError) as e:
                raise TVUnavailable("the client certificate in data/vidaa/ could not be loaded (%s): "
                                    "make it again from your copy of the Hisense app" % type(e).__name__) from None
        return ctx

    def _topic(self, service, name):
        return PROTOCOL["action"].format(service=service, client=self.client_id, name=name)

    def _trace(self, way, topic, payload):
        if not log.isEnabledFor(logging.DEBUG):
            return
        text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload)
        text = re.sub(r'("(?:%s|%s)"\s*:\s*)"[^"]*"' % (PROTOCOL["pin_field"], "|".join(PROTOCOL["token_fields"])),
                      r'\1"(hidden)"', text)
        log.debug("trace %s %s %s", way, topic, text[:600])

    async def _connection(self):
        """The MQTT connection, opened once and kept."""
        if self._mqtt and self._mqtt.alive:
            return self._mqtt
        if time.monotonic() < self._retry_at:
            raise TVUnavailable(self.last_error or "the TV did not answer a moment ago")
        ctx = self._ssl()
        token = self.token
        last, wait = None, self.RETRY_WAIT
        for port in self.PORTS:
            c = Client(self.client_id, username=self.client_id if token else None, password=token,
                       on_message=self._message)
            try:
                await c.connect(self.ip, port, ssl=ctx, timeout=self.CONNECT_TIMEOUT)
                await c.subscribe([t.format(client=self.client_id) for t in PROTOCOL["listen"]])
                self._mqtt, self.last_error = c, None
                if self._stored().get("client_id") != self.client_id:
                    self._keep()   # the same client id next time, so a PIN and a token stay with it
                return c
            except Refused as e:
                wait = self.REFUSED_WAIT
                last = str(e) + (": check the certificate step, and that the TV and this computer agree "
                                 "on the time (docs/VIDAA.md)" if e.code in (4, 5) else "")
            except ssl.SSLError as e:
                last = ("the TV ended the secure handshake (%s): it probably wants the client certificate "
                        "(docs/VIDAA.md)" % (e.reason or type(e).__name__))
            except (MQTTError, OSError) as e:
                last = str(e) or type(e).__name__
                if ctx and not self._certs():
                    last += " (a 2024 or newer TV may want the client certificate: docs/VIDAA.md)"
            await c.close()
        self.last_error, self._retry_at = last, time.monotonic() + wait
        raise TVUnavailable("could not talk to the TV: %s" % last)

    async def _drop(self):
        c, self._mqtt = self._mqtt, None
        if c:
            await c.close()

    def _message(self, topic, payload):
        self._trace("in ", topic, payload)
        try:
            data = json.loads(payload.decode("utf-8")) if payload else None
        except (ValueError, UnicodeDecodeError):
            data = payload.decode("utf-8", "replace")
        name = topic.rstrip("/").rsplit("/", 1)[-1]
        if name == "state" and isinstance(data, dict) and isinstance(data.get("statetype"), str):
            self.statetype = data["statetype"]
            if NOTHING.match(self.statetype) or self.statetype in OFF_STATES:
                self._front = (None, 0.0)
        for fut in self._waiters.pop(name, []):
            if not fut.done():
                fut.set_result(data)

    async def _publish(self, topic, payload):
        c = await self._connection()
        body = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
        self._trace("out", topic, body)
        try:
            await c.publish(topic, body)
        except MQTTError as e:
            await self._drop()
            raise TVUnavailable("the TV closed the connection (%s)" % e) from None

    async def _ask(self, service, name, payload=None, answer=None, timeout=5, topic=None):
        """Publish and wait for the answer whose topic ends in `answer` (default `name`)."""
        fut = asyncio.get_running_loop().create_future()
        self._waiters.setdefault(answer or name, []).append(fut)
        try:
            await self._publish(topic or self._topic(service, name), payload if payload is not None else {})
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            raise TVUnavailable("the TV did not answer %s" % name) from None
        finally:
            lst = self._waiters.get(answer or name)
            if lst and fut in lst:
                lst.remove(fut)

    async def _send(self, service, name, payload=None):
        await self._publish(self._topic(service, name), payload if payload is not None else {})

    # ---------- pairing (the PIN on the TV) ----------
    def pair_start(self):
        """Ask the TV to show its 4 digit PIN."""
        async def go():
            await self._send("ui_service", "vidaa_app_connect", {"device_name": "guest-tv"})
        self._run(go())
        self.pin_shown_at = time.monotonic()
        return True

    def pair_finish(self, pin):
        """Send the PIN, then ask for the token and keep it in data/ (never in git)."""
        pin = str(pin or "").strip()
        if not PIN.match(pin):
            raise ValueError("the PIN is the 4 digits the TV shows")

        async def go():
            # what the TV answers to the PIN is not known yet: the token below is the test of it
            await self._ask("ui_service", "authenticationcode", {PROTOCOL["pin_field"]: pin})
            got = await self._ask("platform_service", "gettoken", {}, topic=PROTOCOL["token"].format(client=self.client_id))
            token = None
            if isinstance(got, dict):
                token = next((got[f] for f in PROTOCOL["token_fields"] if isinstance(got.get(f), str) and got[f]), None)
            if not token:
                self.last_error = "the TV did not accept the PIN, or sent no token"
                raise TVUnavailable("the TV did not accept that PIN (or sent no token): ask it for a new PIN and try again")
            self._keep(token=token)
            self.last_error = None
            await self._drop()   # the next connection logs in with the token
        self._run(go())
        return True

    # ---------- reading the TV ----------
    async def _state(self, timeout=4):
        service, name = PROTOCOL["state_request"]
        data = await self._ask(service, name, {}, answer="state", timeout=timeout)
        return data.get("statetype") if isinstance(data, dict) else None

    def is_on(self):
        try:
            st = self._run(self._state(), 12)
        except TVUnavailable:
            self.statetype = None
            return None
        return None if st is None else st not in OFF_STATES

    def front(self):
        """Where the TV is, as far as guest-tv can tell: None on its home, live TV, an input or standby;
        else the app guest-tv last opened (VIDAA does not say which app is in front), else the state
        the TV reports (a settings menu, an app the TV opened itself)."""
        try:
            self._run(self._state(), 12)   # a fresh look: the pushed state can be a moment late
        except TVUnavailable:
            return None
        st = self.statetype
        if st is None or st in OFF_STATES or NOTHING.match(st):
            return None
        what, at = self._front
        return what if what and time.monotonic() - at < 6 * 3600 else st

    def is_guest(self, front):
        return front == GUEST_FRONT

    def _refresh(self, force=False):
        at, found = self.found
        if found and not force and time.time() - at < 1800 and self.applist:
            return found
        try:
            data = self._run(self._ask("ui_service", "applist", {}, timeout=6), 12)
        except TVUnavailable:
            if found:
                return found
            raise
        rows = data if isinstance(data, list) else []
        if isinstance(data, dict):   # the list may come wrapped in an object
            rows = next((v for v in data.values() if isinstance(v, list)), [])
        listed, found = [], {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            aid, title = str(r.get("appId") or r.get("id") or ""), str(r.get("name") or "").strip()
            if not SAFE_ID.match(aid) or not title:
                continue
            listed.append({"appId": aid, "name": title, "url": str(r.get("url") or ""),
                           "urlType": r.get("urlType"), "storeType": r.get("storeType")})
            gid = BY_NAME.get(plain(title))
            if gid and gid not in found:
                found[gid] = aid
        self.applist = listed
        if listed:
            self.found = (time.time(), found)
        return found

    def app_ids(self):
        return self._refresh()

    def _entry(self, tid):
        """Only an entry the TV itself listed is ever sent back to it."""
        return next((a for a in self.applist if a["appId"] == tid), None) if SAFE_ID.match(str(tid)) else None

    # ---------- doing things ----------
    async def _launch_entry(self, entry, url=None):
        await self._send("ui_service", "launchapp", {
            "appId": entry["appId"], "name": entry["name"], "url": url if url is not None else entry.get("url") or "",
            "urlType": entry.get("urlType"), "storeType": entry.get("storeType")})

    def launch(self, tid):
        if not SAFE_ID.match(str(tid)):
            raise TVUnavailable("that is not an app id the TV gave")
        if not self._entry(tid):
            self._refresh(force=True)
        entry = self._entry(tid)
        if not entry:
            raise TVUnavailable("that app is not on this TV")
        self._run(self._launch_entry(entry))
        self._front = (tid, time.monotonic())

    def button(self, code):
        if not re.fullmatch(r"KEY_[A-Z0-9_]{1,24}", str(code)):
            raise TVUnavailable("not a key this TV takes")
        self._run(self._send(PROTOCOL["key_service"], "sendkey", code))

    def volume(self, up):
        self.button(KEYS["volume_up" if up else "volume_down"])

    def mute(self, on=None):
        self.button(KEYS["mute"])   # the TV does not say whether it is muted: this toggles

    def open_link(self, uri, app_id):
        """No deep link into a show is known on VIDAA: the app opens on its own page."""
        self.open_app(app_id)
        self.quiet(40)   # open_app only waits 20 seconds
        return "app"

    # ---------- guest-tv's page ----------
    def _browser(self):
        return next((a for a in self.applist if plain(a["name"]) in BROWSER_NAMES), None)

    def _tile(self):
        return self._entry(TILE_ID)

    def open_guest_app(self):
        """Open guest-tv's page: its tile where the TV accepted one, else the TV's browser at the page."""
        if not self.page:
            raise TVUnavailable("guest-tv does not know its own address yet (start server.py first)")
        self._refresh(force=True)
        entry = self._tile() or self._browser()
        if not entry:
            if self.applist:
                self.can_open = False
            raise TVUnavailable("the TV lists no guest-tv tile and no web browser to show the welcome "
                                "screen in: use the Guest remote only (docs/VIDAA.md)")
        self._run(self._launch_entry(entry, url=self.page))
        self._front = (GUEST_FRONT, time.monotonic())

    def install_tile(self, wait=8.0):
        """Ask the TV to add a guest-tv tile to its app row. Newer firmware may refuse; then the
        browser stays the way in. True when the tile is in the app list afterwards."""
        if not self.page:
            raise TVUnavailable("guest-tv's page address is not set")
        info = {"Title": TILE_TITLE, "Id": TILE_ID, "URL": self.page, "StoreType": 99}
        self._run(self._send("ui_service", "uievent", {"type": "app_install", "app_info": info}))
        time.sleep(wait)
        self._refresh(force=True)
        return bool(self._tile())


# ---------- tools/tv_app.py ----------
SETUP = """\
1. On the TV: Settings, Network: switch on Wake on LAN if it has it, and note the TV's address.
2. Newer Hisense firmware (2024 on) only lets a phone remote in with the certificate from Hisense's own
   app. Take it from YOUR copy of the app (docs/VIDAA.md) and put client.pem and client.key in data/vidaa/.
3. TV_KIND=vidaa TV_IP=<tv address> .venv/bin/python tools/tv_app.py pair  (the TV shows a 4 digit PIN)
4. Optional on older firmware: tools/tv_app.py install adds a Guest TV tile to the TV's app row.
5. New (Beta): not yet run on a real VIDAA TV."""


def install(ip, url, home_id):
    """Ask the TV for a Guest TV tile. Not needed where the TV's browser can show guest-tv."""
    tv = VidaaTV(ip)
    tv.page = "%s/tv/?tv=%s&brand=vidaa" % (url, home_id)
    try:
        if tv.install_tile():
            print("The TV added a Guest TV tile to its app row.")
        else:
            print("The TV did not add a tile (newer firmware refuses). guest-tv opens in the TV's browser instead.")
    except TVUnavailable as e:
        print("Could not ask the TV: %s" % e)


def uninstall(ip):
    print("Remove the Guest TV tile the way the TV removes any app (highlight it, then the options button).\n"
          "Then delete data/vidaa-%s.key and data/vidaa/ if you want guest-tv to forget this TV." % ip.replace(":", "_"))
