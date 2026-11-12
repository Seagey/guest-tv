"""Test the Panasonic Viera driver (tv_panasonic.py) and its hook, with no real TV and no Claude. A
stand-in Viera runs on this computer for the test, answering the way couch-tv's notes and the public
descriptions of Panasonic's network remote say a real one does, including the encrypted pairing.
The cipher here is written separately from tv_panasonic.py, from the same description.

    .venv/bin/python tools/panasonic_test.py      (needs: cryptography)
"""
import base64, hashlib, hmac, json, os, re, socket, struct, sys, tempfile, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import tvbrands, tvctl, tv_panasonic
from tvbrands import TVUnavailable

TMP = tempfile.mkdtemp(prefix="guest-tv-panasonic-")
tvbrands.DATA = TMP   # the pairing keys go here, not in data/

PIN, APP_ID, SESSION = "5719", "standin-app-id-0042", "778899"
KEYWORD = base64.b64encode(bytes(range(40, 56))).decode()
CHALLENGE = bytes(range(200, 216))
MASK = "15C95AC2B08AA7EB4E228F811E34D04FA54BA7DCAC9879FA8ACDA3FC244F3854"
APPS = ("vc_app'product_id=0010000200000001'Netflix'http://192.0.2.9/icons/netflix.png'"
        "vc_app'product_id=0070000200180001'YouTube'http://192.0.2.9/icons/yt.png'"
        "vc_app'product_id=0387878700000032'Prime Video'http://192.0.2.9/icons/prime.png'"
        "vc_app'product_id=0076010507000001'Some Local App''"
        "vc_app'product_id=xx; reboot'Stan''"           # an unsafe id from the TV: never usable
        "vc_app'resource_id=1063'Web Browser''")
NRC = "urn:panasonic-com:service:p00NetworkControl:1"
DMR = "urn:schemas-upnp-org:service:RenderingControl:1"
SAFE = {"netflix": "product_id=0010000200000001", "youtube": "product_id=0070000200180001",
        "prime-video": "product_id=0387878700000032"}


def tag(xml, name):
    m = re.search(r"<%s>(.*?)</%s>" % (name, name), xml, re.S)
    return m.group(1) if m else None


def pair_keys(ch):
    key = b"".join(bytes(255 - x for x in ch[g:g + 4][::-1]) for g in (0, 4, 8, 12))
    mask, pick = bytes.fromhex(MASK), [2, 3, 0, 1]
    return key, bytes(mask[i] ^ ch[(4 * (i // 4) + pick[i % 4]) & 15] for i in range(32)), ch


def session_keys():
    iv = base64.b64decode(KEYWORD)
    return b"".join(bytes([iv[g + 2], iv[g + 3], iv[g], iv[g + 1]]) for g in (0, 4, 8, 12)), iv * 2, iv


def opened(b64, key, hk, iv):
    raw = base64.b64decode(b64)
    ct, sig = raw[:-32], raw[-32:]
    assert hmac.new(hk, ct, hashlib.sha256).digest() == sig, "bad HMAC"
    d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    plain = d.update(ct) + d.finalize()
    (n,) = struct.unpack(">I", plain[12:16])
    return plain[16:16 + n].decode()


def closed(text, key, hk, iv):
    data = text.encode()
    plain = os.urandom(12) + struct.pack(">I", len(data)) + data
    plain += bytes(16 - len(plain) % 16)
    e = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = e.update(plain) + e.finalize()
    return base64.b64encode(ct + hmac.new(hk, ct, hashlib.sha256).digest()).decode()


V = {"encrypted": False, "log": [], "raw": [], "volume": 20, "muted": False, "urls": [], "challenge": None,
     "dmr_down": False, "connect_back": True}


def answer(action, urn, inner=""):
    return 200, ('<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><u:%sResponse '
                 'xmlns:u="%s">%s</u:%sResponse></s:Body></s:Envelope>' % (action, urn, inner, action))


def fault(code):
    return 500, "<s:Envelope><s:Body><s:Fault><detail><UPnPError><errorCode>%s</errorCode></UPnPError></detail></s:Fault></s:Body></s:Envelope>" % code


def fetch_url(host, port):
    try:
        c = socket.create_connection((host, port), timeout=5)
        data = b""
        while True:
            b = c.recv(4096)
            if not b:
                break
            data += b
        c.close()
        n = data[7]
        V["urls"].append((data[:7], data[8:8 + n].decode(), data[8 + n:]))
    except OSError:
        pass


def nrc(action, args):
    V["log"].append((action, args))
    if action == "X_GetAppList":
        return answer(action, NRC, "<X_AppList>" + APPS.replace("'", "&apos;") + "</X_AppList>")
    if action == "X_ConnectApp" and V["connect_back"]:
        host, port = tag(args, "X_ConnectAddr").rsplit(":", 1)
        threading.Thread(target=fetch_url, args=(host, int(port)), daemon=True).start()
    return answer(action, NRC)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body):
        b = body.encode()
        self.send_response(code)
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.endswith("sdd_0.xml"):
            names = ["X_SendKey", "X_LaunchApp", "X_GetAppList", "X_ConnectApp"]
            if V["encrypted"]:
                names += ["X_DisplayPinCode", "X_RequestAuth", "X_GetEncryptSessionId", "X_EncryptedCommand"]
            return self.send(200, "<scpd>" + "".join("<action><name>%s</name></action>" % n for n in names) + "</scpd>")
        self.send(404, "")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length") or 0)).decode()
        V["raw"].append(body)
        urn, _, action = self.headers.get("SOAPAction", "").strip('"').partition("#")
        m = re.search(r'<u:%s xmlns:u="[^"]+">(.*)</u:%s>' % (action, action), body, re.S)
        args = m.group(1) if m else ""
        code, text = self.route(action, args)
        self.send(code, text)

    def route(self, action, args):
        if self.path.endswith("dmr/control_0"):
            if V["dmr_down"]:
                return fault(401)
            V["log"].append((action, args))
            if action == "GetVolume":
                return answer(action, DMR, "<CurrentVolume>%d</CurrentVolume>" % V["volume"])
            if action == "GetMute":
                return answer(action, DMR, "<CurrentMute>%d</CurrentMute>" % (1 if V["muted"] else 0))
            if action == "SetVolume":
                V["volume"] = int(tag(args, "DesiredVolume"))
            if action == "SetMute":
                V["muted"] = tag(args, "DesiredMute") == "1"
            return answer(action, DMR)
        if action == "X_DisplayPinCode":
            V["challenge"] = CHALLENGE
            return answer(action, NRC, "<X_ChallengeKey>%s</X_ChallengeKey>" % base64.b64encode(CHALLENGE).decode())
        if action == "X_RequestAuth":
            k = pair_keys(V["challenge"])
            if tag(opened(tag(args, "X_AuthInfo"), *k), "X_PinCode") != PIN:
                return fault(600)
            res = closed("<X_ApplicationId>%s</X_ApplicationId><X_Keyword>%s</X_Keyword>" % (APP_ID, KEYWORD), *k)
            return answer(action, NRC, "<X_AuthResult>%s</X_AuthResult>" % res)
        if action == "X_GetEncryptSessionId":
            k = session_keys()
            assert tag(opened(tag(args, "X_EncInfo"), *k), "X_ApplicationId") == APP_ID
            return answer(action, NRC, "<X_EncResult>%s</X_EncResult>" % closed("<X_SessionId>%s</X_SessionId>" % SESSION, *k))
        if action == "X_EncryptedCommand":
            if tag(args, "X_ApplicationId") != APP_ID:
                return fault(401)
            k = session_keys()
            inner = opened(tag(args, "X_EncInfo"), *k)
            if tag(inner, "X_SessionId") != SESSION:
                return fault(403)
            m = re.search(r'<X_OriginalCommand><u:(\w+) xmlns:u="[^"]+">(.*)</u:\1></X_OriginalCommand>', inner, re.S)
            _, text = nrc(m.group(1), m.group(2))
            inner_res = re.sub(r"^.*?<u:\w+Response[^>]*>|</u:\w+Response>.*$", "", text, flags=re.S)
            return answer(action, NRC, "<X_EncResult>%s</X_EncResult>" % closed(inner_res, *k))
        if V["encrypted"]:
            return fault(401)
        return nrc(action, args)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = free_port()
tv_panasonic.PanasonicTV.PORT = PORT
srv = None


def power(on):
    """The stand-in's port: open while the TV is on, shut when it is off (as a real Viera's is)."""
    global srv
    if on and not srv:
        ThreadingHTTPServer.allow_reuse_address = True
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    elif not on and srv:
        srv.shutdown()
        srv.server_close()
        srv = None


ok = bad = 0


def check(name, cond):
    global ok, bad
    print(("PASS  " if cond else "FAIL  ") + name)
    ok, bad = (ok + 1, bad) if cond else (ok, bad + 1)


def wait_for(fn, t=6):
    end = time.monotonic() + t
    while time.monotonic() < end:
        if fn():
            return True
        time.sleep(0.05)
    return False


def sent(action):
    return [a for n, a in V["log"] if n == action]


def mk(ip="127.0.0.1"):
    tv = tv_panasonic.PanasonicTV(ip)
    tv.BROWSER_WAIT = 0.1
    tv.page = "http://192.0.2.7:5410/tv/?tv=guest&brand=panasonic"
    return tv


# ---------------------------------------------------------------- an older set: no pairing
print("older set")
power(False)
tv = mk()
check("no answer: is_on None", tv.is_on() is None)
try:
    tv.app_ids()
    check("app_ids with the TV off raises TVUnavailable", False)
except TVUnavailable:
    check("app_ids with the TV off raises TVUnavailable", True)
power(True)
check("port answers: is_on True", tv.is_on() is True)
check("front is None (the TV cannot say)", tv.front() is None and tv.sees_front is False)
check("pairing is a PIN", tv.pairing == "pin" and tv.pair_start() is False)
ids = tv.app_ids()
check("app_ids by the names the TV lists", ids == SAFE)
check("an unsafe id the TV listed is not offered", all(re.match(r"^product_id=[0-9A-Za-z]{16}$", v) for v in ids.values())
      and "stan" not in ids)
check("installed() reads from it", sorted(a["id"] for a in tv.installed()) == sorted(SAFE))
V["log"].clear()
tv.launch(SAFE["netflix"])
check("launch sends the app's keyword", any(SAFE["netflix"] in a for a in sent("X_LaunchApp")))
for bad_id in ("product_id=xx; reboot", "resource_id=12<x>", "'; rm -rf /", None, "netflix"):
    try:
        tv.launch(bad_id)
        check("unsafe id %r refused" % (bad_id,), False)
    except TVUnavailable:
        check("unsafe id %r refused" % (bad_id,), True)
check("nothing unsafe reached the TV", len(sent("X_LaunchApp")) == 1)
V["log"].clear()
for name in tvctl.KEYS:
    if name in ("mute", "volume_up", "volume_down", "home"):
        continue
    tv.key(name)
want = [tv_panasonic.KEYS[n] for n in tvctl.KEYS if n not in ("mute", "volume_up", "volume_down", "home")]
check("every guest key reaches the TV as its NRC key", [tag(a, "X_KeyEvent") for a in sent("X_SendKey")] == want)
try:
    tv.key("power")
    check("a key outside the table is refused", False)
except KeyError:
    check("a key outside the table is refused", True)
check("nothing from the refused key was sent", len(sent("X_SendKey")) == len(want))
V["volume"] = 20
tv.key("volume_up")
check("volume up reads the real level and sets 21", V["volume"] == 21)
tv.key("volume_down", times=3)
check("volume down three times sets 18", V["volume"] == 18)
V["volume"] = 100
tv.key("volume_up")
check("volume stops at 100", V["volume"] == 100)
tv.mute(True)
check("mute on", V["muted"] is True)
tv.key("mute")
check("the mute key toggles it off", V["muted"] is False)
V["dmr_down"] = True
V["log"].clear()
tv.key("volume_up")
tv.key("mute")
check("when the set does not say, the remote's own volume and mute keys are used",
      [tag(a, "X_KeyEvent") for a in sent("X_SendKey")] == ["NRC_VOLUP-ONOFF", "NRC_MUTE-ONOFF"])
V["dmr_down"] = False
V["log"].clear()
tv.open_app("youtube")
check("open_app launches it", any(SAFE["youtube"] in a for a in sent("X_LaunchApp")) and tv.quiet_until > time.monotonic())
V["log"].clear()
check("open_link opens the app on its own page", tv.open_link("https://www.netflix.com/title/80057281", "netflix") == "app"
      and any(SAFE["netflix"] in a for a in sent("X_LaunchApp")))
check("open_link quiets the hook for 40 s", tv.quiet_until - time.monotonic() > 30)
try:
    tv.open_link("https://x.example.com/", None)
    check("open_link with no app is refused", False)
except TVUnavailable:
    check("open_link with no app is refused", True)
V["log"].clear()
V["urls"].clear()
tv.open_guest_app()
check("open_guest_app opens the browser, hands over the address",
      "resource_id=1063" in " ".join(sent("X_LaunchApp")) and len(sent("X_ConnectApp")) == 1
      and wait_for(lambda: len(V["urls"]) == 1))
head, url, tail = V["urls"][0]
check("the page address is exactly guest-tv's page, framed as the TV expects",
      url == tv.page and head == tv_panasonic.PROTOCOL["url_head"] and tail == b"\x00")
check("the page has no key in it", "key" not in url.lower() and "token" not in url.lower())
tv.page = None
try:
    tv.open_guest_app()
    check("open_guest_app with no page is refused", False)
except TVUnavailable:
    check("open_guest_app with no page is refused", True)
tv.page = "http://192.0.2.7:5410/tv/?" + "a" * 300
try:
    tv.open_guest_app()
    check("an address over 255 characters is refused", False)
except TVUnavailable:
    check("an address over 255 characters is refused", True)
tv.page = "ftp://192.0.2.7/x"
try:
    tv.open_guest_app()
    check("a non http address is refused", False)
except TVUnavailable:
    check("a non http address is refused", True)
tv.page = mk().page
V["connect_back"] = False
tv_panasonic.PROTOCOL["connect_timeout"] = 0.5
try:
    tv.open_guest_app()
    check("a TV that never comes for the address gives a plain error", False)
except TVUnavailable as e:
    check("a TV that never comes for the address gives a plain error", "never came" in str(e))
V["connect_back"] = True

# ---------------------------------------------------------------- an encrypted set: pairing with a PIN
print("encrypted set")
V["encrypted"], V["log"] = True, []
tv = mk()
tv.found = (0.0, {})
try:
    tv.key("up")
    check("an unpaired encrypted set says to pair first", False)
except TVUnavailable as e:
    check("an unpaired encrypted set says to pair first", "pairing" in str(e))
check("pair_start asks the TV for a PIN", tv.pair_start() is True and V["challenge"] == CHALLENGE)
for badpin in ("abc", "12", "123456", "", None, "12 4"):
    try:
        tv.pair_finish(badpin)
        check("PIN %r is refused before it is sent" % (badpin,), False)
    except TVUnavailable:
        check("PIN %r is refused before it is sent" % (badpin,), True)
V["raw"].clear()
try:
    tv.pair_finish("0000")
    check("a wrong PIN is refused by the TV", False)
except TVUnavailable as e:
    check("a wrong PIN is refused by the TV", "wrong" in str(e) and "0000" not in str(e))
check("nothing was kept after a wrong PIN", not os.path.exists(tv.token_file))
check("the PIN never went over the wire in the clear", not any("0000" in b or PIN in b for b in V["raw"]))
check("pair_finish with the right PIN", tv.pair_finish(PIN) is True)
kept = open(tv.token_file).read()
check("the keys are kept at 0600 in data/", oct(os.stat(tv.token_file).st_mode & 0o777) == "0o600"
      and os.path.dirname(tv.token_file) == TMP and APP_ID in kept)
check("hide() removes every secret from a SOAP message",
      "(hidden)" in tv_panasonic.hide("<X_PinCode>%s</X_PinCode><X_Keyword>%s</X_Keyword>" % (PIN, KEYWORD))
      and PIN not in tv_panasonic.hide("<X_PinCode>%s</X_PinCode>" % PIN) and KEYWORD not in tv_panasonic.hide("<X_Keyword>%s</X_Keyword>" % KEYWORD))
V["log"].clear()
V["raw"].clear()
tv.key("up")
tv.key("ok")
check("sealed keys reach the TV", [tag(a, "X_KeyEvent") for a in sent("X_SendKey")] == ["NRC_UP-ONOFF", "NRC_ENTER-ONOFF"])
check("no key name travelled in the clear", not any("NRC_UP" in b for b in V["raw"]))
check("encrypted app list", tv.app_ids() == SAFE)
tv.launch(SAFE["netflix"])
check("encrypted launch", any(SAFE["netflix"] in a for a in sent("X_LaunchApp")))
tv._enc = (tv._enc[0], tv._enc[1])
tv._enc = ("000000", 5)   # a session the TV does not know: it is refused once, then a new one is made
V["log"].clear()
tv.key("down")
check("a refused session is replaced once and the key goes through", [tag(a, "X_KeyEvent") for a in sent("X_SendKey")] == ["NRC_DOWN-ONOFF"])
V["urls"].clear()
tv.open_guest_app()
check("open_guest_app works inside the encrypted wrapper", wait_for(lambda: len(V["urls"]) == 1) and V["urls"][0][1] == tv.page)
V["muted"] = False
tv.mute()
check("mute over RenderingControl on an encrypted set", V["muted"] is True)
V["encrypted"] = False

# ---------------------------------------------------------------- the hook
print("hook")
V["log"].clear()
V["urls"].clear()
tv = mk()
tv.SETTLE = 0.2
power(False)
stop = threading.Event()
th = threading.Thread(target=tvbrands.watch, args=(tv,), kwargs={"every": 0.2, "stop": stop}, daemon=True)
th.start()
time.sleep(0.6)
check("TV off: nothing opened", not V["urls"])
power(True)
check("off, then on: the hook opens guest-tv in the browser", wait_for(lambda: len(V["urls"]) == 1) and V["urls"][0][1] == tv.page)
check("the hook logged it, saying the TV cannot confirm", wait_for(lambda: any("cannot say" in l for l in tv.log)))
time.sleep(0.8)
tv.launch(SAFE["netflix"])
time.sleep(0.8)
check("TV left on with an app open: not opened again", len(V["urls"]) == 1)
power(False)
time.sleep(0.6)
tv.quiet(2)   # the guest has just asked for something
power(True)
time.sleep(1.2)
check("a guest command just ran (quiet): the hook leaves it alone", len(V["urls"]) == 1 and any("left alone" in l for l in tv.log))
power(False)
time.sleep(2.2)   # the quiet time is over
power(True)
check("later switch on opens guest-tv again", wait_for(lambda: len(V["urls"]) == 2))
tv.can_open = False
stop.set()
th.join(3)
tv2 = mk()
tv2.can_open = False
stop2 = threading.Event()
threading.Thread(target=tvbrands.watch, args=(tv2, 0.05, stop2), daemon=True).start()
check("can_open False: the hook does nothing and says why", wait_for(lambda: any("cannot show" in l for l in tv2.log)))
stop2.set()

# ---------------------------------------------------------------- the registry
print("registry")
check("tvbrands.make builds the driver", isinstance(tvbrands.make("panasonic", "127.0.0.1"), tv_panasonic.PanasonicTV))
check("tvctl.tv_for builds it too", tvctl.tv_for("127.0.0.1", "panasonic").kind == "panasonic")

power(False)
print("\n%d passed, %d failed" % (ok, bad))
sys.exit(1 if bad else 0)
