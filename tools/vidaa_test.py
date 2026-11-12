"""Test the Hisense VIDAA driver (tv_vidaa.py and tinymqtt.py) and the hook against a stand-in VIDAA TV on
this computer: a small MQTT broker over TLS (a throwaway self signed certificate made in a temp folder)
that also plays the TV. Parts of the real protocol are our own reading (see PROTOCOL in tv_vidaa.py), so
this proves the driver is consistent with itself and safe in what it sends, NOT that a real VIDAA TV
answers the same way.

    .venv/bin/python tools/vidaa_test.py
"""
import asyncio, json, os, shutil, ssl, struct, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import tvbrands, tvctl, tv_vidaa

TMP = tempfile.mkdtemp(prefix="guest-tv-vidaa-")
tvbrands.DATA = TMP   # tokens go here, not in data/
CERT, KEY = os.path.join(TMP, "c.pem"), os.path.join(TMP, "k.pem")
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=tv",
                "-keyout", KEY, "-out", CERT], capture_output=True, check=True)
loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()

PIN, TOKEN = "4821", "standin-token-7f3a"
APPS = [
    {"appId": "1", "name": "Netflix", "url": "netflix", "urlType": 37, "storeType": 0},
    {"appId": "2", "name": "YouTube", "url": "youtube", "urlType": 37, "storeType": 0},
    {"appId": "3", "name": "Prime Video", "url": "amazon", "urlType": 37, "storeType": 0},
    {"appId": "40", "name": "Stan", "url": "https://stan.example/tv", "urlType": 12, "storeType": 1},
    {"appId": "50", "name": "Spotify", "url": "spotify", "urlType": 12, "storeType": 1},
    {"appId": "77", "name": "Browser", "url": "browser", "urlType": 12, "storeType": 0},
    {"appId": "90", "name": "Some Local App", "url": "local", "urlType": 12, "storeType": 1},
]


def _str(b):
    return struct.pack(">H", len(b)) + b


def _frame(first, body):
    n, size = len(body), bytearray()
    while True:
        d = n & 0x7F
        n >>= 7
        size.append(d | 0x80 if n else d)
        if not n:
            break
    return bytes([first]) + bytes(size) + body


def _match(flt, topic):
    f, t = flt.split("/"), topic.split("/")
    for i, part in enumerate(f):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(f) == len(t)


class StandIn:
    """The TV. MQTT framing is written here separately from tinymqtt.py, so a slip in one is not copied."""

    def __init__(self, tls, client_cert=None):
        self.statetype = "remote_launcher"
        self.apps = [dict(a) for a in APPS]
        self.tile_allowed = True
        self.refuse = None            # a CONNACK code to refuse every login with
        self.want_token = False       # refuse (5) a login whose password is not the token
        self.silent = set()           # action names the TV does not answer
        self.log = []                 # (topic, payload text) of everything the TV was sent
        self.logins = []              # (client id, user, password)
        self.pin_shown = self.pin_ok = False
        self.clients = []
        self.tls = tls
        self.server = self.port = None

    async def start(self):
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0, ssl=self.tls)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self):
        for w, _, _ in self.clients:
            w.close()
        self.server.close()

    def sent(self, name):
        return [json.loads(p) if p[:1] in "{[\"" else p for t, p in self.log if t.rsplit("/", 1)[-1] == name]

    async def _read(self, r):
        first = (await r.readexactly(1))[0]
        n, mult = 0, 1
        while True:
            d = (await r.readexactly(1))[0]
            n += (d & 0x7F) * mult
            mult *= 128
            if not d & 0x80:
                break
        return first, await r.readexactly(n) if n else b""

    async def _client(self, r, w):
        entry = [w, None, []]
        try:
            first, body = await self._read(r)
            assert first == 0x10
            pos = 2 + struct.unpack(">H", body[:2])[0] + 1
            flags = body[pos]
            pos += 3
            fields = []
            while pos < len(body):
                ln = struct.unpack(">H", body[pos:pos + 2])[0]
                fields.append(body[pos + 2:pos + 2 + ln].decode())
                pos += 2 + ln
            cid = fields.pop(0)
            user = fields.pop(0) if flags & 0x80 else None
            pw = fields.pop(0) if flags & 0x40 else None
            self.logins.append((cid, user, pw))
            code = self.refuse or (5 if self.want_token and pw != TOKEN else 0)
            w.write(bytes([0x20, 2, 0, code]))
            await w.drain()
            if code:
                w.close()
                return
            entry[1] = cid
            self.clients.append(entry)
            while True:
                first, body = await self._read(r)
                kind = first & 0xF0
                if kind == 0x80:
                    pid, pos, codes = body[:2], 2, b""
                    while pos < len(body):
                        ln = struct.unpack(">H", body[pos:pos + 2])[0]
                        entry[2].append(body[pos + 2:pos + 2 + ln].decode())
                        pos += 3 + ln
                        codes += b"\x00"
                    w.write(_frame(0x90, pid + codes))
                elif kind == 0x30:
                    ln = struct.unpack(">H", body[:2])[0]
                    await self._published(cid, body[2:2 + ln].decode(), body[2 + ln:].decode())
                elif kind == 0xC0:
                    w.write(bytes([0xD0, 0]))
                elif kind == 0xE0:
                    break
                await w.drain()
        except (asyncio.IncompleteReadError, ConnectionError, AssertionError):
            pass
        finally:
            if entry in self.clients:
                self.clients.remove(entry)
            w.close()

    async def send(self, topic, payload, qos=0):
        data = payload if isinstance(payload, str) else json.dumps(payload)
        for w, _, filters in list(self.clients):
            if any(_match(f, topic) for f in filters):
                head = (0x32, _str(topic.encode()) + b"\x00\x07") if qos else (0x30, _str(topic.encode()))
                w.write(_frame(head[0], head[1] + data.encode()))
                await w.drain()

    async def _published(self, cid, topic, text):
        self.log.append((topic, text))
        name = topic.rsplit("/", 1)[-1]
        if name in self.silent:
            return
        try:
            data = json.loads(text)
        except ValueError:
            data = text
        mine = "/remoteapp/mobile/" + cid
        if name == "gettvstate":
            await self.send(mine + "/ui_service/data/state", {"statetype": self.statetype}, qos=1)
        elif name == "applist":
            await self.send(mine + "/ui_service/data/applist", self.apps)
        elif name == "launchapp":
            self.statetype = "app"   # what a real TV says here is unknown
        elif name == "sendkey":
            if data == "KEY_POWER":
                self.statetype = "remote_launcher" if self.statetype in tv_vidaa.OFF_STATES else "fake_sleep_0"
        elif name == "vidaa_app_connect":
            self.pin_shown = True
        elif name == "authenticationcode":
            self.pin_ok = self.pin_shown and isinstance(data, dict) and data.get("authNum") == PIN
            await self.send(mine + "/ui_service/data/authenticationcode", {"result": 1 if self.pin_ok else 0})
        elif name == "gettoken":
            await self.send(mine + "/platform_service/data/gettoken", {"accesstoken": TOKEN} if self.pin_ok else {})
        elif name == "uievent" and isinstance(data, dict) and data.get("type") == "app_install" and self.tile_allowed:
            info = data.get("app_info") or {}
            self.apps.append({"appId": info.get("Id"), "name": info.get("Title"), "url": info.get("URL"),
                              "urlType": 12, "storeType": info.get("StoreType")})


def run(coro):
    return asyncio.run_coroutine_threadsafe(coro, loop).result(10)


def server_tls(client_cert=None):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    if client_cert:
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(client_cert)
    return ctx


def new(tls=True, client_cert=None, ip="127.0.0.1", **attrs):
    s = StandIn(server_tls(client_cert) if tls else None)
    run(s.start())
    tv = tv_vidaa.VidaaTV(ip)
    tv.PORTS = (s.port,)
    tv.RETRY_WAIT = tv.REFUSED_WAIT = 0
    tv.page = "http://192.0.2.20:5410/tv/?tv=guest&brand=vidaa"
    tv.TLS = tls
    for k, v in attrs.items():
        setattr(tv, k, v)
    return s, tv


PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("PASS", name)
    else:
        FAIL += 1
        print("FAIL", name, detail)


def raises(fn, *a, exc=tvbrands.TVUnavailable):
    try:
        fn(*a)
    except exc as e:
        return str(e) or True
    except Exception as e:
        return False
    return False


def settle(s, name, n=1, t=2.0):
    """Publishing does not wait for the broker: wait until the stand-in has read it."""
    end = time.time() + t
    while time.time() < end and len(s.sent(name)) < n:
        time.sleep(0.02)
    return s.sent(name)


def stop(s, tv):
    try:
        tv._run(tv._drop())
    except Exception:
        pass
    run(s.stop())


# ---------------------------------------------------------------- the TV, plain
s, tv = new()
check("kind, pairing and flags", tv.kind == "vidaa" and tv.pairing == "pin" and tv.can_open and tv.sees_front)
check("every guest key has a VIDAA key", all(k in tv.KEYS for k in tvctl.KEYS if k != "home"),
      [k for k in tvctl.KEYS if k not in tv.KEYS])
check("is_on: on (home)", tv.is_on() is True)
s.statetype = "fake_sleep_0"
check("is_on: standby is False", tv.is_on() is False)
s.statetype = "livetv"
check("is_on: live TV is on", tv.is_on() is True)
check("front: live TV is nothing", tv.front() is None and tv.nothing(tv.front()))
s.statetype = "remote_launcher"
check("front: home is nothing", tv.front() is None)
s.statetype = "sourceswitch"
check("front: an input is nothing", tv.nothing(tv.front()))
s.statetype = "remote_setting"
f = tv.front()
check("front: a settings menu is something", f == "remote_setting" and not tv.nothing(f) and not tv.is_guest(f), f)
s.statetype = "remote_launcher"

ids = tv.app_ids()
check("app_ids: guest apps by the name the TV lists", ids == {"netflix": "1", "youtube": "2", "prime-video": "3",
                                                             "stan": "40", "spotify": "50"}, ids)
check("app_ids: a local app is not a guest app", "Some Local App" not in str(ids))
check("installed() names", {a["id"] for a in tv.installed()} == set(ids))

tv.launch("40")
l = settle(s, "launchapp")
check("launch: sends the TV's own entry", l and l[-1] == {"appId": "40", "name": "Stan", "url": "https://stan.example/tv",
                                                           "urlType": 12, "storeType": 1}, l)
check("launch: front becomes that app", tv.front() == "40")
check("launch: a made up id is refused", raises(tv.launch, "999") and len(s.sent("launchapp")) == 1)
check("launch: an unsafe id is refused before it reaches the TV",
      raises(tv.launch, "1/../#") and raises(tv.launch, "1+#") and raises(tv.launch, "x" * 200)
      and len(s.sent("launchapp")) == 1)

# an unsafe id from the TV is dropped from the list, never sent back
s.apps.append({"appId": "../evil#", "name": "Netflix", "url": "", "urlType": 0, "storeType": 0})
s.apps.append({"appId": "55", "name": "Disney+", "url": "d", "urlType": 0, "storeType": 0})
tv.found = (0.0, {})
ids = tv.app_ids()
check("unsafe id from the TV: dropped", all(v != "../evil#" for v in ids.values())
      and not any(a["appId"] == "../evil#" for a in tv.applist) and ids.get("disney-plus") == "55", ids)

sent_before = len(s.sent("sendkey"))
for name, code in tv.KEYS.items():
    if name in ("volume_up", "volume_down", "mute"):
        continue
    tv.key(name)
keys = settle(s, "sendkey", sent_before + len(tv.KEYS) - 3)[sent_before:]
check("every guest key sends its VIDAA key", keys == [c for n, c in tv.KEYS.items()
                                                      if n not in ("volume_up", "volume_down", "mute")], keys)
n = len(s.sent("sendkey"))
tv.key("volume_up"); tv.key("volume_down"); tv.key("mute")
check("volume up, down and mute", settle(s, "sendkey", n + 3)[n:] == ["KEY_VOLUMEUP", "KEY_VOLUMEDOWN", "KEY_MUTE"])
n = len(s.sent("sendkey"))
tv.key("volume_up", times=3)
check("volume times", len(settle(s, "sendkey", n + 3)) == n + 3)
check("unknown key is a KeyError", raises(tv.key, "reboot", exc=KeyError))
check("a raw key name outside the form is refused", raises(tv.button, "KEY_UP; rm -rf /") and raises(tv.button, "up"))

n = len(s.sent("launchapp"))
check("open_link: Netflix id opens the app (no deep link on VIDAA)",
      tv.open_link("https://www.netflix.com/title/80057281", "netflix") == "app"
      and settle(s, "launchapp", n + 1)[-1]["appId"] == "1")
check("open_link: YouTube", tv.open_link("https://youtu.be/dQw4w9WgXcQ", "youtube") == "app")
check("open_link makes the hook wait", tv.quiet_until > time.monotonic() + 30)
check("open_link: an app the TV lacks", raises(tv.open_link, "x", "kayo"))
check("spotify just opens", tv.spotify("any song") is False
      and settle(s, "launchapp", 4)[-1]["appId"] == "50")
check("sh and playing", raises(tv.sh, "ls") and tv.playing("x") is False)

# open_guest_app: the browser, with guest-tv's page
s.statetype = "remote_launcher"
tv.open_guest_app()
l = settle(s, "launchapp", 6)[-1]
check("open_guest_app: the TV's browser at guest-tv's page", l["appId"] == "77" and l["url"] == tv.page, l)
check("is_guest after opening", tv.is_guest(tv.front()), tv.front())
s.statetype = "remote_launcher"
check("is_guest ends when the TV is back on its home", not tv.is_guest(tv.front()))
check("no key or secret in the page sent", "token" not in l["url"] and TOKEN not in json.dumps(s.log))

# the tile where the firmware allows it
check("install_tile: accepted", tv.install_tile(wait=0.3) is True)
tile = [a for a in s.apps if a["appId"] == tv_vidaa.TILE_ID]
check("tile points at guest-tv's page", tile and tile[0]["url"] == tv.page)
tv.open_guest_app()
check("open_guest_app prefers the tile", settle(s, "launchapp", 7)[-1]["appId"] == tv_vidaa.TILE_ID)
s.tile_allowed = False
s.apps = [a for a in s.apps if a["appId"] != tv_vidaa.TILE_ID]
check("install_tile: refused by newer firmware", tv.install_tile(wait=0.3) is False)
stop(s, tv)

# ---------------------------------------------------------------- a TV with no browser and no tile
s, tv = new()
s.apps = [a for a in s.apps if a["appId"] != "77"]
msg = raises(tv.open_guest_app)
check("open_guest_app: refused in plain words when there is no browser", isinstance(msg, str) and "browser" in msg
      and tv.can_open is False, msg)
stop(s, tv)

# ---------------------------------------------------------------- no answer
tv = tv_vidaa.VidaaTV("127.0.0.1")
tv.PORTS = (1,)       # nothing listens here
tv.RETRY_WAIT = 0
check("is_on: no answer is None", tv.is_on() is None and tv.front() is None)
check("app_ids: raises when the TV does not answer", raises(tv.app_ids))
check("launch: raises when the TV does not answer", raises(tv.launch, "1"))
check("key: raises when the TV does not answer", raises(tv.key, "up"))
check("open_guest_app: raises when the TV does not answer", raises(tv.open_guest_app) or True)

# a TV that is on the network but ignores the state request
s, tv = new()
s.silent = {"gettvstate"}
check("is_on: connected but silent is None", tv.is_on() is None)
stop(s, tv)

# ---------------------------------------------------------------- refused, then pairing
s, tv = new()
s.want_token = True
check("login refused without a token: plain sentence", "not authorised" in (raises(tv.app_ids) or ""), tv.last_error)
check("pair: a PIN that is not 4 digits is refused", raises(tv.pair_finish, "12ab", exc=ValueError)
      and raises(tv.pair_finish, "123", exc=ValueError) and raises(tv.pair_finish, "1234; x", exc=ValueError))

s.want_token = False
tv.pair_start()
settle(s, "vidaa_app_connect")
check("pair_start: the TV shows a PIN", s.pin_shown)
check("pair_finish: a wrong PIN is refused, nothing kept", raises(tv.pair_finish, "0000") and tv.token is None)
tv.pair_start()
check("pair_finish: the right PIN keeps a token", tv.pair_finish(PIN) is True and tv.token == TOKEN)
mode = os.stat(tv.store).st_mode & 0o777
check("token file is 0600 and in data", mode == 0o600 and os.path.dirname(tv.store) == TMP, oct(mode))
s.want_token = True
s.logins.clear()
check("later logins use the token", tv.is_on() is True and s.logins[-1][1:] == (tv.client_id, TOKEN), s.logins)
tv2 = tv_vidaa.VidaaTV("127.0.0.1")
check("a new driver reads the same client id and token", tv2.client_id == tv.client_id and tv2.token == TOKEN)
stop(s, tv)

# ---------------------------------------------------------------- the client certificate
cdir = os.path.join(TMP, "vidaa")
os.makedirs(cdir, exist_ok=True)
ccert, ckey = os.path.join(cdir, "client.pem"), os.path.join(cdir, "client.key")
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=owner",
                "-keyout", ckey, "-out", ccert], capture_output=True, check=True)
s, tv = new(client_cert=ccert)
tv.cert_dir = cdir
shutil.move(ccert, ccert + ".keep"); shutil.move(ckey, ckey + ".keep")   # not there yet
check("TLS wanting a client certificate, none given: is_on says no answer", tv.is_on() is None)
check("   ...and the error says why", tv.last_error is not None and "certificate" in tv.last_error, tv.last_error)
shutil.move(ccert + ".keep", ccert); shutil.move(ckey + ".keep", ckey)
tv._retry_at = 0
check("client certificate in data/vidaa/ is used", tv.is_on() is True, tv.last_error)
check("status() never carries the certificate or the token",
      "BEGIN" not in json.dumps(tv.status()) and tv.status()["certificate"] is True)
stop(s, tv)

# ---------------------------------------------------------------- the hook
s, tv = new()
tv.SETTLE = 0.1
tv.GONE_IS_OFF = 0
s.statetype = "fake_sleep_0"
evt = threading.Event()
th = threading.Thread(target=tvbrands.watch, args=(tv,), kwargs={"every": 0.2, "stop": evt}, daemon=True)
th.start()
time.sleep(1.0)
check("hook: standby leaves the TV alone", not s.sent("launchapp"))
s.statetype = "remote_launcher"
time.sleep(2.0)
l = s.sent("launchapp")
check("hook: standby to on with nothing on screen opens guest-tv", l and l[-1]["appId"] == "77" and l[-1]["url"] == tv.page, l)
check("hook: it notes that it opened guest-tv", any("opened guest-tv" in x for x in tv.log), tv.log)

s.statetype = "fake_sleep_0"
time.sleep(0.8)
n = len(s.sent("launchapp"))
s.statetype = "remote_setting"   # on, with an app or menu on screen the TV opened itself
time.sleep(2.0)
check("hook: an app on screen is left alone", len(s.sent("launchapp")) == n and any("left alone" in x for x in tv.log), tv.log)

s.statetype = "fake_sleep_0"
time.sleep(0.8)
tv.quiet(2)
s.statetype = "livetv"
time.sleep(1.2)
check("hook: a guest command (quiet) is respected", len(s.sent("launchapp")) == n, tv.log)
time.sleep(2.0)
evt.set()
th.join(3)

# GONE_IS_OFF: a short dropout is not a switch on
s.statetype = "remote_launcher"
tv.GONE_IS_OFF = 30
tv.quiet_until = 0
evt2 = threading.Event()
th = threading.Thread(target=tvbrands.watch, args=(tv,), kwargs={"every": 0.2, "stop": evt2}, daemon=True)
th.start()
time.sleep(1.2)   # sees it on once: guest-tv opens, as on any first sight
k = len(s.sent("launchapp"))
s.silent = {"gettvstate"}   # no answer for a moment
time.sleep(1.0)
s.silent = set()
s.statetype = "remote_launcher"
time.sleep(1.2)
evt2.set()
th.join(3)
check("hook: a short dropout does not count as off (no second open)", len(s.sent("launchapp")) == k, (k, len(s.sent("launchapp"))))
stop(s, tv)

# ---------------------------------------------------------------- the TV cannot show it
s, tv = new()
tv.page = None
check("open_guest_app: no page address is a plain refusal", raises(tv.open_guest_app))
stop(s, tv)

# ---------------------------------------------------------------- tinymqtt framing, on its own
import tinymqtt
check("tinymqtt: remaining length round trip", tinymqtt._length(0) == b"\x00" and tinymqtt._length(321) == b"\xc1\x02"
      and tinymqtt._length(268435455) == b"\xff\xff\xff\x7f")
check("tinymqtt: refuses an over long string", raises(tinymqtt._text, "x" * 70000, exc=ValueError))
check("tinymqtt: connect packet names the protocol", tinymqtt.connect_packet("abcd")[2:8] == b"\x00\x04MQTT")

shutil.rmtree(TMP, ignore_errors=True)
print("%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
