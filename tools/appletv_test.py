"""Test the Apple TV driver (tv_appletv.py) and the hook with no real Apple TV and no Claude. A stand-in
Apple TV runs on 127.0.0.1 for the test: a small TCP server that speaks the Companion link the way the
public protocol notes describe it (pairing with a PIN, pair verify, sealed OPACK messages), ported from
couch-tv's tests/appletv_standin.py. It is written from the same notes as the driver, so passing proves
they agree with each other and survive the failure paths, not that a real Apple TV answers the same way.

    .venv/bin/python tools/appletv_test.py      (needs: pip install cryptography)
"""
import asyncio, json, os, secrets, stat, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import tvbrands, tvctl
import tv_appletv as A
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

TMP = tempfile.mkdtemp(prefix="guest-tv-appletv-")
tvbrands.DATA = TMP                                   # the pairing keys go here, not in data/
A.AppleTV.SIGNING = os.path.join(TMP, "no-signing.xcconfig")
A.HOME_XCCONFIG = os.path.join(TMP, "build", "tvos", "Home.xcconfig")
os.environ.pop("GUEST_TV_APPLETV_APP", None)

GUEST = "dev.guesttv.appletv.test"
APPS = {"com.netflix.Netflix": "Netflix", "com.google.ios.youtube": "YouTube", "com.apple.TVWatchList": "TV",
        "au.example.stan": "Stan", GUEST: "Guest TV", "com.example.other": "Some Other App",
        "bad id;rm -rf": "Kayo"}           # an id that must never go back to the Apple TV


# ---------------------------------------------------------------- stand-in Apple TV (its own loop)
sloop = asyncio.new_event_loop()
threading.Thread(target=sloop.run_forever, daemon=True).start()


def srun(coro):
    return asyncio.run_coroutine_threadsafe(coro, sloop).result(10)


class StandIn:
    def __init__(self):
        self.pin = "%04d" % secrets.randbelow(10000)
        self.attention = A.AWAKE
        self.log = []               # ("hid", code, down/up), ("launch", bundle), ("ask", name)
        self.paired = {}            # client id -> public key
        self.fail_launch = set()
        self.ltsk = Ed25519PrivateKey.generate()
        self.atv_id = b"standin-apple-tv"
        self.apps = dict(APPS)
        self.deaf = False           # close every connection at once (gone from the network)
        self.writers = set()
        self.connections = 0

    async def start(self):
        self.server = await asyncio.start_server(self._conn, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    def close_all(self):
        """Close every open connection, on the stand-in's own loop (transports are not thread safe)."""
        async def shut():
            for w in list(self.writers):
                w.close()
        srun(shut())

    async def _read(self, r, key, n):
        h = await r.readexactly(4)
        body = await r.readexactly(int.from_bytes(h[1:], "big"))
        if key:
            body = ChaCha20Poly1305(key).decrypt(n.to_bytes(12, "little"), body, h)
        return h[0], body

    @staticmethod
    def _write(w, ftype, payload, key=None, n=0):
        if key:
            header = bytes([ftype]) + (len(payload) + 16).to_bytes(3, "big")
            payload = ChaCha20Poly1305(key).encrypt(n.to_bytes(12, "little"), payload, header)
        w.write(bytes([ftype]) + len(payload).to_bytes(3, "big") + payload)

    async def _conn(self, r, w):
        self.connections += 1
        if self.deaf:
            w.close()
            return
        self.writers.add(w)
        try:
            await self._serve(r, w)
        except Exception:
            pass
        finally:
            self.writers.discard(w)
            w.close()

    async def _serve(self, r, w):
        in_key = out_key = None
        in_n = out_n = 0
        srp = verify = None
        while True:
            ftype, body = await self._read(r, in_key, in_n)
            if in_key:
                in_n += 1
            msg = A.opack_decode(body)
            if ftype == A.F_PS_START:
                srp = self._srp_start()
                self._write(w, A.F_PS_START, A.opack_encode({"_pd": A.tlv_encode([
                    (A.T_SEQ, b"\2"), (A.T_PUBLIC_KEY, A._i2b(srp["B"])), (A.T_SALT, srp["salt"])])}))
            elif ftype == A.F_PS_NEXT:
                t = A.tlv_decode(msg["_pd"])
                reply = self._srp_m3(srp, t) if t[A.T_SEQ] == b"\3" else self._srp_m5(srp, t)
                self._write(w, A.F_PS_NEXT, A.opack_encode({"_pd": reply}))
            elif ftype == A.F_PV_START:
                t = A.tlv_decode(msg["_pd"])
                eph = X25519PrivateKey.generate()
                pub = A.raw_public(eph)
                shared = eph.exchange(X25519PublicKey.from_public_bytes(t[A.T_PUBLIC_KEY]))
                key = A.hkdf(shared, b"Pair-Verify-Encrypt-Salt", b"Pair-Verify-Encrypt-Info")
                sig = self.ltsk.sign(pub + self.atv_id + t[A.T_PUBLIC_KEY])
                sub = A.tlv_encode([(A.T_IDENTIFIER, self.atv_id), (A.T_SIGNATURE, sig)])
                verify = (shared, key, t[A.T_PUBLIC_KEY], pub)
                self._write(w, A.F_PV_START, A.opack_encode({"_pd": A.tlv_encode([
                    (A.T_SEQ, b"\2"), (A.T_PUBLIC_KEY, pub), (A.T_ENCRYPTED, A.seal(key, b"PV-Msg02", sub))])}))
            elif ftype == A.F_PV_NEXT:
                shared, key, cpub, spub = verify
                t = A.tlv_decode(msg["_pd"])
                inner = A.tlv_decode(A.unseal(key, b"PV-Msg03", t[A.T_ENCRYPTED]))
                ltpk = self.paired.get(inner[A.T_IDENTIFIER].decode())
                ok = False
                if ltpk:
                    try:
                        Ed25519PublicKey.from_public_bytes(ltpk).verify(inner[A.T_SIGNATURE], cpub + inner[A.T_IDENTIFIER] + spub)
                        ok = True
                    except Exception:
                        pass
                if not ok:
                    self._write(w, A.F_PV_NEXT, A.opack_encode({"_pd": A.tlv_encode([(A.T_SEQ, b"\4"), (A.T_ERROR, b"\2")])}))
                    continue
                self._write(w, A.F_PV_NEXT, A.opack_encode({"_pd": A.tlv_encode([(A.T_SEQ, b"\4")])}))
                in_key, out_key = A.hkdf(shared, b"", b"ClientEncrypt-main"), A.hkdf(shared, b"", b"ServerEncrypt-main")
                in_n = out_n = 0
            elif ftype == A.F_E_OPACK and in_key:
                for reply in self._handle(msg):
                    self._write(w, A.F_E_OPACK, A.opack_encode(reply), out_key, out_n)
                    out_n += 1
            await w.drain()

    def _srp_start(self):
        salt = secrets.token_bytes(16)
        v = pow(A.SRP_G, A.srp_x(salt, b"Pair-Setup", self.pin.encode()), A.SRP_N)
        b = A._b2i(secrets.token_bytes(64)) % A.SRP_N
        return {"salt": salt, "v": v, "b": b, "B": (A.srp_k() * v + pow(A.SRP_G, b, A.SRP_N)) % A.SRP_N}

    def _srp_m3(self, s, t):
        a_pub = A._b2i(t[A.T_PUBLIC_KEY])
        u = A.srp_u(a_pub, s["B"])
        S = pow(a_pub * pow(s["v"], u, A.SRP_N), s["b"], A.SRP_N)
        s["key"] = A._h(A._i2b(S))
        m1 = A.srp_m1(b"Pair-Setup", s["salt"], a_pub, s["B"], s["key"])
        if m1 != t[A.T_PROOF]:
            return A.tlv_encode([(A.T_SEQ, b"\4"), (A.T_ERROR, b"\2")])    # wrong PIN
        return A.tlv_encode([(A.T_SEQ, b"\4"), (A.T_PROOF, A.srp_m2(a_pub, m1, s["key"]))])

    def _srp_m5(self, s, t):
        enc = A.hkdf(s["key"], b"Pair-Setup-Encrypt-Salt", b"Pair-Setup-Encrypt-Info")
        inner = A.tlv_decode(A.unseal(enc, b"PS-Msg05", t[A.T_ENCRYPTED]))
        x = A.hkdf(s["key"], b"Pair-Setup-Controller-Sign-Salt", b"Pair-Setup-Controller-Sign-Info")
        Ed25519PublicKey.from_public_bytes(inner[A.T_PUBLIC_KEY]).verify(
            inner[A.T_SIGNATURE], x + inner[A.T_IDENTIFIER] + inner[A.T_PUBLIC_KEY])
        self.paired[inner[A.T_IDENTIFIER].decode()] = inner[A.T_PUBLIC_KEY]
        ltpk = A.raw_public(self.ltsk)
        ax = A.hkdf(s["key"], b"Pair-Setup-Accessory-Sign-Salt", b"Pair-Setup-Accessory-Sign-Info")
        sub = A.tlv_encode([(A.T_IDENTIFIER, self.atv_id), (A.T_PUBLIC_KEY, ltpk),
                            (A.T_SIGNATURE, self.ltsk.sign(ax + self.atv_id + ltpk))])
        return A.tlv_encode([(A.T_SEQ, b"\6"), (A.T_ENCRYPTED, A.seal(enc, b"PS-Msg06", sub))])

    def _handle(self, msg):
        name, c, xid = msg.get("_i"), msg.get("_c") or {}, msg.get("_x")
        self.log.append(("ask", name))
        if name == "_hidC":
            self.log.append(("hid", c["_hidC"], "down" if c["_hBtS"] == 1 else "up"))
            if c["_hBtS"] == 2 and c["_hidC"] == A.HID["sleep"]:
                self.attention = A.ASLEEP
            if c["_hBtS"] == 2 and c["_hidC"] == A.HID["wake"]:
                self.attention = A.AWAKE
            return []                       # button events get no reply
        if name == "_launchApp":
            b = c.get("_bundleID")
            self.log.append(("launch", b))
            if b in self.fail_launch or b not in self.apps:
                return [{"_t": 4, "_x": xid, "_em": "no such app"}]
            return [{"_t": 3, "_x": xid, "_c": {}}]
        if name == "FetchAttentionState":
            return [{"_t": 2, "_x": 999, "_i": "SomeEvent", "_c": {}},       # an event first: skipped
                    {"_t": 3, "_x": xid, "_c": {"state": self.attention}}]
        if name == "FetchLaunchableApplicationsEvent":
            return [{"_t": 3, "_x": xid, "_c": dict(self.apps)}]
        if name == "_sessionStart":
            return [{"_t": 3, "_x": xid, "_c": {"_sid": 7}}]
        if name == "TVRCSessionStart":
            return [{"_t": 4, "_x": xid, "_em": "unsupported"}]     # older tvOS: the driver must carry on
        return [{"_t": 3, "_x": xid, "_c": {}}]


# ---------------------------------------------------------------- checks
passed, failed = 0, 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print("PASS", name)
    else:
        failed += 1
        print("FAIL", name, detail)


def raises(fn, exc=Exception, has=""):
    try:
        fn()
    except exc as e:
        return has.lower() in str(e).lower()
    except Exception as e:
        print("   (raised %s: %s)" % (type(e).__name__, e))
        return False
    return False


def wait_for(cond, secs=4.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def settle():
    time.sleep(0.25)   # presses get no answer: give the stand-in a moment to read the last one


def hids(s, since=0):
    return [(r[1], r[2]) for r in s.log[since:] if r[0] == "hid"]


def launches(s, since=0):
    return [r[1] for r in s.log[since:] if r[0] == "launch"]


# ---- the binary formats
for v in [None, True, False, 0, 39, 40, 255, 256, 70000, 2 ** 40, 1.5, "", "hi", "x" * 40, "x" * 300,
          b"", b"\0\1", b"y" * 40, [], [1, "a"], list(range(20)), {}, {"_i": "a", "_c": {"k": [1, 2]}},
          {str(i): i for i in range(20)}]:
    if A.opack_decode(A.opack_encode(v)) != v:
        check("OPACK round trip %r" % (v,), False)
        break
else:
    check("OPACK round trips every kind of value", True)
check("OPACK known bytes and a back reference", A.opack_encode({"a": 1}) == b"\xe1\x41a\x09"
      and A.opack_decode(b"\xd2\x41a\xa0") == ["a", "a"])
check("OPACK garbage is an error, not a crash",
      all(raises(lambda b=b: A.opack_decode(b), A.AppleTVError) for b in (b"", b"\xd5\x08", b"\x61", b"\xff")))
long_tlv = A.tlv_decode(A.tlv_encode([(A.T_SEQ, b"\1"), (A.T_PUBLIC_KEY, b"k" * 600)]))
check("TLV8 splits and joins long values", long_tlv[A.T_PUBLIC_KEY] == b"k" * 600 and long_tlv[A.T_SEQ] == b"\1")
check("the SRP group is the 3072 bit one, generator 5", A.SRP_N.bit_length() == 3072 and A.SRP_G == 5
      and pow(2, A.SRP_N - 1, A.SRP_N) == 1)

# ---- set up: one stand-in Apple TV, the driver pointed at it by moving the class port
s = StandIn()
srun(s.start())
A.AppleTV.PORT = s.port
check("tvbrands.make builds the Apple TV driver", type(tvbrands.make("appletv", "127.0.0.1")).__name__ == "AppleTV")
tv = tvctl.tv_for("127.0.0.1", "appletv")
tv.SETTLE = 0.1
check("address:port is understood", A.AppleTV("192.0.2.5:49200").port == 49200 and A.AppleTV("192.0.2.5").port is None)
check("kind, pairing and flags", tv.kind == "appletv" and tv.pairing == "pin" and tv.sees_front is False and tv.can_open)

# ---- not paired yet
check("not paired: is_on says no answer", tv.is_on() is None)
check("not paired: a key says to pair first", raises(lambda: tv.key("up"), tvbrands.TVUnavailable, "not paired"))

# ---- pairing with the PIN on screen
check("pair_finish refuses a PIN that is not 4 digits", raises(lambda: tv.pair_finish("12a4"), tvbrands.TVUnavailable, "4 digits")
      and raises(lambda: tv.pair_finish("12345"), tvbrands.TVUnavailable, "4 digits"))
check("pair_finish before pair_start is refused", raises(lambda: tv.pair_finish("1234"), tvbrands.TVUnavailable, "pin first"))
tv.pair_start()
wrong = "%04d" % ((int(s.pin) + 1) % 10000)
check("a wrong PIN is refused", raises(lambda: tv.pair_finish(wrong), tvbrands.TVUnavailable, "did not accept"))
check("a wrong PIN keeps nothing", not os.path.exists(tv.key_file) and not s.paired)
tv.pair_start()
check("the right PIN pairs", tv.pair_finish(s.pin) is True and len(s.paired) == 1)
mode = stat.S_IMODE(os.stat(tv.key_file).st_mode)
saved = open(tv.key_file).read()
check("the keys are kept in data/ as 0600, without the PIN", tv.key_file.startswith(TMP) and mode == 0o600
      and json.loads(saved).keys() >= {"client_id", "ltsk", "atv_id", "atv_ltpk"} and s.pin not in json.dumps(json.loads(saved)["client_id"]))

# ---- power: awake, screensaver, asleep, gone
s.attention = A.AWAKE
check("is_on: awake is on (an event before the answer is skipped)", tv.is_on() is True)
s.attention = A.SCREENSAVER
check("is_on: the screensaver counts as on", tv.is_on() is True)
s.attention = A.ASLEEP
check("is_on: asleep is standby", tv.is_on() is False)
s.deaf = True
s.close_all()
check("is_on: gone is no answer", tv.is_on() is None)
s.deaf = False
s.attention = A.AWAKE
check("is_on: back again after the Apple TV dropped the connection", tv.is_on() is True)
n = s.connections
s.close_all()
time.sleep(0.3)
tv.key("up")
settle()
check("a kept connection the Apple TV closed is opened again by itself", s.connections > n and hids(s)[-2:] == [(1, "down"), (1, "up")],
      "%s %s" % (s.connections - n, hids(s)[-2:]))
check("front: the link cannot say, so None", tv.front() is None)
check("is_guest and nothing: unknown front counts as nothing", tv.nothing(None) and not tv.is_guest(None))

# ---- apps
ids = tv.app_ids()
check("app_ids: bundle ids from couch-tv's table", ids.get("netflix") == "com.netflix.Netflix"
      and ids.get("youtube") == "com.google.ios.youtube" and ids.get("apple-tv") == "com.apple.TVWatchList")
check("app_ids: the rest by the name the Apple TV lists", ids.get("stan") == "au.example.stan")
check("app_ids: an unsafe id from the Apple TV is dropped", "kayo" not in ids and "bad id;rm -rf" not in tv.listed[1])
i = len(s.log)
tv.open_app("netflix")
check("launch: opens Netflix by its bundle id", launches(s, i) == ["com.netflix.Netflix"])
check("launch: an unsafe id never reaches the Apple TV", raises(lambda: tv.launch("bad id;rm -rf"), ValueError)
      and raises(lambda: tv.launch("x"), ValueError) and launches(s, i) == ["com.netflix.Netflix"])
s.fail_launch.add("au.example.stan")
check("launch: a refused app is a plain error", raises(lambda: tv.open_app("stan"), tvbrands.TVUnavailable, "would not open"))
s.fail_launch.clear()
check("open_app: an app the Apple TV does not have", raises(lambda: tv.open_app("binge"), tvbrands.TVUnavailable, "not on this TV"))
check("installed lists the guest apps", {a["id"] for a in tv.installed()} == {"netflix", "youtube", "apple-tv", "stan"})

# ---- every guest key
i = len(s.log)
expect = []
for name in tvctl.KEYS:
    if name == "mute":
        check("key mute: plain refusal (no mute on this link)", raises(lambda: tv.key("mute"), tvbrands.TVUnavailable, "no mute"))
        continue
    if name == "home":
        j = len(s.log)
        tv.key("home")
        check("key home: opens guest-tv's app", launches(s, j) == [GUEST])
        continue
    tv.key(name)
    expect += [(A.HID[A.KEYS[name]], "down"), (A.HID[A.KEYS[name]], "up")]
settle()
got = hids(s, i)
check("every other guest key is a press and release of the right button", got == expect, "%s != %s" % (got, expect))
check("an unknown key is a KeyError", raises(lambda: tv.key("explode"), KeyError))
i = len(s.log)
tv.key("volume_up", times=3)
tv.volume(False)
settle()
check("volume: the remote's volume buttons, times capped", hids(s, i) == [(8, "down"), (8, "up")] * 3 + [(9, "down"), (9, "up")])
check("mute: plain refusal", raises(lambda: tv.mute(True), tvbrands.TVUnavailable, "no mute"))

# ---- shows: the app opens, not the show
i = len(s.log)
before = time.monotonic()
r1 = tv.open_link("https://www.netflix.com/title/80057281", "netflix")
r2 = tv.open_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube")
r3 = tv.open_link("intent://whatever", "stan")
check("open_link: Netflix, YouTube and others open the app", (r1, r2, r3) == ("app", "app", "app")
      and launches(s, i) == ["com.netflix.Netflix", "com.google.ios.youtube", "au.example.stan"])
check("open_link: quiet for 40 seconds", tv.quiet_until - before > 35)
check("spotify: opens the app (not on this Apple TV here)", raises(lambda: tv.spotify("chill"), tvbrands.TVUnavailable))

# ---- guest-tv's own app
check("guest_id: found on the Apple TV by its start", tv.guest_id() == GUEST)
i = len(s.log)
tv.open_guest_app()
check("open_guest_app launches guest-tv's app", launches(s, i) == [GUEST])
with open(A.AppleTV.SIGNING, "w") as f:
    f.write("DEVELOPMENT_TEAM = ABCDE12345\nPRODUCT_BUNDLE_IDENTIFIER = dev.guesttv.appletv.mine\n")
check("guest_id: the owner's Signing.mine.xcconfig wins", tv.guest_id() == "dev.guesttv.appletv.mine")
check("open_guest_app: refuses plainly when that app is not on the Apple TV",
      raises(lambda: tv.open_guest_app(), tvbrands.TVUnavailable, "not on this apple tv yet"))
with open(A.AppleTV.SIGNING, "w") as f:
    f.write("PRODUCT_BUNDLE_IDENTIFIER = dev.guesttv.appletv.yourname\n")
check("guest_id: the example's placeholder id is ignored", tv.guest_id() == GUEST)
os.remove(A.AppleTV.SIGNING)
os.environ["GUEST_TV_APPLETV_APP"] = "bad id;x"
check("guest_id: an unsafe override is ignored", tv.guest_id() == GUEST)
os.environ.pop("GUEST_TV_APPLETV_APP")

# ---- sleep and wake
tv.sleep()
check("sleep puts it to sleep", wait_for(lambda: s.attention == A.ASLEEP) and tv.is_on() is False)
tv.wake()
check("wake wakes it", wait_for(lambda: s.attention == A.AWAKE) and tv.is_on() is True)

# ---- the hook
tv.quiet_until = 0.0
s.attention = A.ASLEEP
stop = threading.Event()
th = threading.Thread(target=tvbrands.watch, args=(tv,), kwargs={"every": 0.2, "stop": stop}, daemon=True)
th.start()
time.sleep(0.8)
i = len(s.log)
s.attention = A.AWAKE
check("hook: asleep to awake opens guest-tv", wait_for(lambda: launches(s, i) == [GUEST]), "%s %s" % (launches(s, i), tv.log))
check("hook: notes it asked (it cannot see the screen)", wait_for(lambda: "asked it to open guest-tv" in " ".join(tv.log)))
tv.open_app("netflix")
i = len(s.log)
time.sleep(1.2)
check("hook: leaves an app alone while the Apple TV stays on", launches(s, i) == [])
tv.quiet_until = 0.0
s.attention = A.SCREENSAVER
time.sleep(0.6)
s.attention = A.AWAKE
time.sleep(0.8)
check("hook: waking from the screensaver does not open guest-tv over a paused show", launches(s, i) == [])
tv.quiet(20)
s.attention = A.ASLEEP
time.sleep(0.6)
s.attention = A.AWAKE
check("hook: respects quiet after a guest's command", wait_for(lambda: "left alone" in " ".join(tv.log)) and launches(s, i) == [])
tv.quiet_until = 0.0
tv.GONE_IS_OFF = 5
s.deaf = True
s.close_all()
time.sleep(1.0)
s.deaf = False
time.sleep(1.0)
check("hook: a short silence is a Wi-Fi dropout, not a switch on", launches(s, i) == [])
s.attention = A.ASLEEP
time.sleep(0.6)
s.attention = A.AWAKE
check("hook: opens guest-tv again on the next wake", wait_for(lambda: launches(s, i) == [GUEST]), "%s %s" % (launches(s, i), tv.log))
stop.set()
th.join(3)
check("hook: never leaks the keys into its notes", not any(json.loads(saved)["ltsk"] in line for line in tv.log))

# ---- an Apple TV that was reset (its keys changed): a plain "pair again"
other = StandIn()
other.pin = s.pin
srun(other.start())
tv2 = A.AppleTV("127.0.0.1:%d" % other.port)
tvbrands._keep(tv2.key_file, saved)
other.paired = dict(s.paired)
check("a different Apple TV on the same address: pair again", tv2.attention() is None
      and raises(lambda: tv2.key("up"), tvbrands.TVUnavailable, "pair again"))

# ---- putting Guest TV on the Apple TV (no Xcode run here)
check("SETUP says what the owner does once", "Signing.mine.xcconfig" in A.SETUP and "7 days" in A.SETUP)
path = A.write_home("http://192.0.2.20:5410", "guest")
text = open(path).read()
check("write_home: the computer's address and home for the build", path.startswith(TMP)
      and "GUESTTV_HOST = 192.0.2.20:5410" in text and "GUESTTV_SCHEME = http" in text and "GUESTTV_HOME = guest" in text)
check("write_home: a bad address or home is refused", raises(lambda: A.write_home("http://x/; rm", "guest"), SystemExit)
      and raises(lambda: A.write_home("http://192.0.2.20:5410", "Guest Room"), SystemExit))
check("build, install and uninstall exist for tools/tv_app.py", all(callable(getattr(A, f)) for f in ("build", "install", "uninstall")))

print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
