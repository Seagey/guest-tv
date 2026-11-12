"""Panasonic Viera TVs for guest-tv: tv_kind "panasonic". New (Beta).

Cut down from couch-tv's bridge/panasonic.py (github.com/Seagey/couch-tv, docs/PANASONIC.md) to what
guest-tv uses. Written from Panasonic's network remote protocol as it is publicly described and checked
against a stand-in Viera on the computer (tools/panasonic_test.py) so far. First reports from real TVs
are wanted: facts seen only in public write ups, never on a set we ran, are marked UNCONFIRMED below.

Which sets: Viera TVs on My Home Screen (about 2015 to 2019) and older Vieras with network control
(about 2012 on). Not Panasonic's Google TV models (those are normal guest-tv Android TVs), nor its Fire
TV, Roku or TiVo models.

How a Viera is reached: plain HTTP on port 55000 with SOAP requests.

  nrc/ddd.xml        the device description
  nrc/sdd_0.xml      the action list of the remote service. X_GetEncryptSessionId in it means an
                     encrypted set (about 2018 on): pair once with a PIN the TV shows
  nrc/control_0      keys (X_SendKey), apps (X_GetAppList, X_LaunchApp), the browser hand off
                     (X_ConnectApp), pairing and the encrypted wrapper
  dmr/control_0      volume and mute (UPnP RenderingControl), never encrypted

Encrypted sets: after the PIN the TV gives an application id and a key word, kept in data/ at 0600
(never in git). Every remote command then goes inside X_EncryptedCommand, AES-128-CBC with an
HMAC-SHA256. Needs the "cryptography" package, only on those sets.

The hook: the TV cannot say what is on screen (sees_front is False), and a Viera reopens its last screen
when it starts. So just after the TV comes on (SETTLE) guest-tv opens its page in the TV's own web
browser, and never checks that it opened or takes over later. It is a page that opens itself, not a
true home screen: the browser's bar stays visible and the remote's Home button still opens Panasonic's
home (Home on the Guest remote brings guest-tv back).

What it cannot do: say which app is in front, deep links into a show (apps open on their own page),
the Guest profile picker, Spotify search (it just opens), screenshots, typing.
"""
import base64, hashlib, hmac, html, json, re, secrets, socket, struct, threading, time, urllib.error, urllib.request
from xml.sax.saxutils import escape

import tvbrands, tvctl
from tvbrands import TVUnavailable, _Base

SETUP = [
    "On the TV: Menu, Network, TV Remote App Settings (the name differs by year). Switch on TV Remote.",
    "Give the TV a fixed address in your router. Wired works better than Wi-Fi.",
    "Newer sets (about 2018 on): run 'pair'. The TV shows a four digit PIN, type it in once.",
    "Then 'open': the TV's browser opens guest-tv. Nothing is installed on the TV.",
]

NRC_URN = "urn:panasonic-com:service:p00NetworkControl:1"
DMR_URN = "urn:schemas-upnp-org:service:RenderingControl:1"

# Every path, name and byte layout in one place, so a first owner's trace can correct it here.
PROTOCOL = {
    "nrc": ("nrc/control_0", NRC_URN),
    "dmr": ("dmr/control_0", DMR_URN),
    "description": "nrc/ddd.xml",
    "actions": "nrc/sdd_0.xml",
    "encrypted_marker": "X_GetEncryptSessionId",
    # sent as they are even on an encrypted set (the pairing and the session request)
    "plain_actions": ("X_DisplayPinCode", "X_RequestAuth", "X_GetEncryptSessionId"),
    "wrong_pin": 600,                        # SOAP errorCode for a wrong PIN
    "pin": r"^\d{4}$",                       # UNCONFIRMED: four digits on the sets described
    # UNCONFIRMED: the app list's layout (records split on "vc_app", fields on an apostrophe).
    "app_type": "vc_app",
    "app_split": "vc_app",
    "app_field": "'",
    # Opening a web page. All UNCONFIRMED on a real set:
    #  1. X_LaunchApp with this keyword opens the browser,
    #  2. after browser_wait seconds, X_ConnectApp gives the TV an address of ours (a listener),
    #  3. the TV connects to it and we send url_head, one length byte, the address, url_tail.
    "browser_keyword": "resource_id=1063",
    "connect_keyword": "guest-tv",
    "connect_timeout": 8.0,
    "url_head": bytes([0xF4, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00]),
    "url_tail": b"\x00",
    "url_max": 255,                          # one length byte
    # Encryption (sets with X_GetEncryptSessionId), from the public description of the scheme.
    # Pairing keys from the TV's challenge (16 bytes): AES key = each 4 byte group reversed and inverted,
    # HMAC key = this mask XORed with the challenge, shuffled 2,3,0,1 within each group of four.
    "hmac_mask": bytes.fromhex("15C95AC2B08AA7EB4E228F811E34D04FA54BA7DCAC9879FA8ACDA3FC244F3854"),
    "sequence": "{:08d}",
}

# guest key name -> Panasonic key. The first group is from the public key lists; the rest is UNCONFIRMED.
KEYS = {
    "up": "NRC_UP-ONOFF", "down": "NRC_DOWN-ONOFF", "left": "NRC_LEFT-ONOFF", "right": "NRC_RIGHT-ONOFF",
    "ok": "NRC_ENTER-ONOFF", "back": "NRC_RETURN-ONOFF",
    "volume_up": "NRC_VOLUP-ONOFF", "volume_down": "NRC_VOLDOWN-ONOFF", "mute": "NRC_MUTE-ONOFF",
    # "home" opens guest-tv (_Base.key); this is Panasonic's own home, kept for completeness
    "home": "NRC_HOME-ONOFF",
    # UNCONFIRMED from here
    "play_pause": "NRC_PLAY-ONOFF", "fast_forward": "NRC_FF-ONOFF", "rewind": "NRC_REW-ONOFF",
    "next": "NRC_FF-ONOFF", "previous": "NRC_REW-ONOFF",
}
LAUNCH = re.compile(r"^(product_id=[0-9A-Za-z]{16}|resource_id=\d{1,8})$")   # an app keyword, before it is sent
SECRET_TAGS = ("X_PinCode", "X_ChallengeKey", "X_AuthInfo", "X_AuthResult", "X_Keyword", "X_EncInfo",
               "X_EncResult", "X_ApplicationId", "X_SessionId")

# The names a Viera lists an app under, besides the name in tvctl.APPS (from couch-tv's bridge/apps.py).
EXTRA_NAMES = {"prime-video": ["Amazon Prime Video"], "abc-iview": ["iview"], "apple-tv": ["Apple TV+"],
               "10play": ["10", "10 play"], "kayo": ["Kayo Sports"], "disney-plus": ["Disney Plus"],
               "paramount-plus": ["Paramount Plus"]}
BY_NAME = {}
for _a in tvctl.APPS:
    for _n in [_a["name"]] + EXTRA_NAMES.get(_a["id"], []):
        BY_NAME.setdefault(tvbrands.plain(_n), _a["id"])


def field(xml, tag):
    """The text of the first <tag> in a SOAP answer, unescaped, or None. Namespaces are ignored."""
    m = re.search(r"<(?:[\w-]+:)?%s(?:\s[^>]*)?>(.*?)</(?:[\w-]+:)?%s>" % (tag, tag), xml or "", re.S)
    return html.unescape(m.group(1)) if m else None


def hide(text):
    """A SOAP message with every PIN, key, session and application id replaced, for anything printed."""
    for t in SECRET_TAGS:
        text = re.sub(r"(<(?:[\w-]+:)?%s>).*?(</(?:[\w-]+:)?%s>)" % (t, t), r"\1(hidden)\2", text, flags=re.S)
    return text


def envelope(action, urn, args=""):
    return ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            '<u:%s xmlns:u="%s">%s</u:%s></s:Body></s:Envelope>' % (action, urn, args, action))


# ---------- the encrypted sets' cipher (couch-tv's pairing_keys, session_keys, seal, unseal) ----------
def _aes(key, iv):
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        raise TVUnavailable("this Panasonic wants encryption, which needs the cryptography package: "
                            ".venv/bin/pip install cryptography") from None
    return Cipher(algorithms.AES(bytes(key)), modes.CBC(bytes(iv)))


def pairing_keys(challenge):
    """(AES key, HMAC key) for the PIN step, from the TV's 16 byte challenge."""
    if len(challenge) != 16:
        raise TVUnavailable("the TV's PIN challenge is not 16 bytes")
    aes_key = bytearray()
    for g in range(0, 16, 4):
        aes_key += bytes(~b & 0xFF for b in reversed(challenge[g:g + 4]))
    mask, order = PROTOCOL["hmac_mask"], (2, 3, 0, 1)
    return bytes(aes_key), bytes(mask[i] ^ challenge[(i - i % 4 + order[i % 4]) % 16] for i in range(32))


def session_keys(keyword):
    """(IV, AES key, HMAC key) for commands, from the key word the TV gave when it was paired."""
    iv = base64.b64decode(keyword)
    if len(iv) != 16:
        raise TVUnavailable("the stored key word is not 16 bytes: pair again")
    return iv, bytes(iv[g + o] for g in range(0, 16, 4) for o in (2, 3, 0, 1)), iv + iv


def seal(text, key, hmac_key, iv):
    """12 random bytes, the length (4 bytes, big endian), the text, zero padding; AES-CBC; HMAC on the end."""
    data = text.encode("utf-8")
    plain = secrets.token_bytes(12) + struct.pack(">I", len(data)) + data
    plain += b"\0" * (16 - len(plain) % 16)
    enc = _aes(key, iv).encryptor()
    ct = enc.update(plain) + enc.finalize()
    return base64.b64encode(ct + hmac.new(hmac_key, ct, hashlib.sha256).digest()).decode()


def unseal(b64, key, hmac_key, iv):
    """The text inside a sealed answer. The HMAC is checked and taken off when it is there."""
    try:
        data = base64.b64decode(b64 or "", validate=True)
    except ValueError:
        raise TVUnavailable("the TV's encrypted answer is not base64") from None
    if len(data) >= 48 and hmac.compare_digest(hmac.new(hmac_key, data[:-32], hashlib.sha256).digest(), data[-32:]):
        data = data[:-32]
    if not data or len(data) % 16:
        raise TVUnavailable("the TV's encrypted answer has the wrong length")
    dec = _aes(key, iv).decryptor()
    plain = dec.update(data) + dec.finalize()
    return plain[16:].split(b"\0", 1)[0].decode("utf-8", "replace")


class PanasonicRefused(TVUnavailable):
    """The TV answered, but refused. .code is the SOAP errorCode (or the HTTP status)."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class PanasonicTV(_Base):
    kind = "panasonic"
    KEYS = KEYS
    PORT = 55000
    pairing = "pin"
    sees_front = False        # the TV cannot say what is on screen
    SETTLE = 6.0              # a Viera reopens its last screen when it comes on
    GONE_IS_OFF = 0
    BROWSER_WAIT = 3.0        # seconds between opening the browser and handing it the address
    ENCRYPTED = None          # True or False to skip reading it from the TV

    def __init__(self, ip):
        super().__init__(ip)
        self.token_file = tvbrands._token_file("panasonic", ip)
        self.cmd_lock = threading.RLock()
        self.encrypted = self.ENCRYPTED
        self.services = {}
        self.listed = []          # [{"launch", "name"}] every app the TV listed
        self.listed_at = 0.0
        self._enc = None          # (session id, sequence number) on an encrypted set
        self._challenge = None    # the PIN step's challenge, in memory only

    # ---------- what is kept for this TV ----------
    def _creds(self):
        try:
            d = json.loads(tvbrands._read(self.token_file) or "{}")
        except ValueError:
            return None
        a, k = d.get("app_id"), d.get("keyword")
        return (a, k) if isinstance(a, str) and a and isinstance(k, str) and k else None

    def _need_creds(self):
        c = self._creds()
        if not c:
            raise TVUnavailable("this TV wants pairing first: run tools/tv_app.py pair (docs/PANASONIC.md)")
        return c

    # ---------- HTTP and SOAP ----------
    def _url(self, path):
        return "http://%s:%d/%s" % (self.ip, self.PORT, path)

    def _get(self, path):
        try:
            with urllib.request.urlopen(self._url(path), timeout=5) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise PanasonicRefused("the TV answered %s for %s" % (e.code, path), e.code) from None
        except (OSError, ValueError):
            raise TVUnavailable("the TV did not answer") from None

    def _post(self, service, action, args=""):
        path, urn = PROTOCOL[service]
        req = urllib.request.Request(self._url(path), data=envelope(action, urn, args).encode("utf-8"), headers={
            "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": '"%s#%s"' % (urn, action)}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            code = field(body, "errorCode")
            raise PanasonicRefused("the TV refused %s (%s)" % (action, code or e.code),
                                   int(code) if code and code.isdigit() else e.code) from None
        except (OSError, ValueError):
            raise TVUnavailable("the TV did not answer %s" % action) from None

    def detect(self):
        """Read the action list once: is this an encrypted set that needs pairing?"""
        if self.encrypted is None:
            self.encrypted = PROTOCOL["encrypted_marker"] in self._get(PROTOCOL["actions"])
        return self.encrypted

    def _soap(self, service, action, args=""):
        """One SOAP request. On an encrypted set, remote commands go inside X_EncryptedCommand."""
        if service != "nrc" or action in PROTOCOL["plain_actions"] or not self.detect():
            return self._post(service, action, args)
        with self.cmd_lock:
            for attempt in (0, 1):
                if not self._enc:
                    self._new_session()
                try:
                    return self._encrypted(action, args)
                except PanasonicRefused as e:
                    if attempt or e.code == PROTOCOL["wrong_pin"]:
                        raise
                    self._enc = None   # the session may have run out: one new one, then give up

    def _encrypted(self, action, args):
        app_id, keyword = self._need_creds()
        iv, key, hk = session_keys(keyword)
        sid, seq = self._enc
        seq += 1
        self._enc = (sid, seq)
        inner = ("<X_SessionId>%s</X_SessionId><X_SequenceNumber>%s</X_SequenceNumber>"
                 '<X_OriginalCommand><u:%s xmlns:u="%s">%s</u:%s></X_OriginalCommand>'
                 % (escape(sid), PROTOCOL["sequence"].format(seq), action, NRC_URN, args, action))
        text = self._post("nrc", "X_EncryptedCommand", "<X_ApplicationId>%s</X_ApplicationId><X_EncInfo>%s</X_EncInfo>"
                          % (escape(app_id), seal(inner, key, hk, iv)))
        res = field(text, "X_EncResult")
        return text if res is None else unseal(res, key, hk, iv)

    def _new_session(self):
        app_id, keyword = self._need_creds()
        iv, key, hk = session_keys(keyword)
        text = self._post("nrc", "X_GetEncryptSessionId", "<X_ApplicationId>%s</X_ApplicationId><X_EncInfo>%s</X_EncInfo>"
                          % (escape(app_id), seal("<X_ApplicationId>%s</X_ApplicationId>" % escape(app_id), key, hk, iv)))
        sid = field(unseal(field(text, "X_EncResult") or "", key, hk, iv), "X_SessionId")
        if not sid:
            raise TVUnavailable("the TV gave no session (pair again if this keeps happening)")
        self._enc = (sid, 0)

    # ---------- pairing (the PIN on the TV, encrypted sets only) ----------
    def pair_start(self):
        """Ask the TV to show its PIN. False on a set that needs no pairing."""
        if self.is_on() is None:
            raise TVUnavailable("the TV is not answering")
        if not self.detect():
            return False
        text = self._post("nrc", "X_DisplayPinCode", "<X_DeviceName>guest-tv</X_DeviceName>")
        try:
            self._challenge = base64.b64decode(field(text, "X_ChallengeKey") or "", validate=True)
        except ValueError:
            self._challenge = None
        if not self._challenge or len(self._challenge) != 16:
            self._challenge = None
            raise TVUnavailable("the TV showed no PIN challenge")
        return True

    def pair_finish(self, pin):
        """Send the PIN sealed with the challenge; keep the application id and key word (0600, never in git)."""
        pin = str(pin or "").strip()
        if not re.match(PROTOCOL["pin"], pin):
            raise TVUnavailable("the PIN is the four digits the TV shows")
        if not self._challenge:
            raise TVUnavailable("ask the TV for a PIN first")
        key, hk = pairing_keys(self._challenge)
        iv = self._challenge
        try:
            text = self._post("nrc", "X_RequestAuth", "<X_AuthInfo>%s</X_AuthInfo>"
                              % seal("<X_PinCode>%s</X_PinCode>" % pin, key, hk, iv))
        except PanasonicRefused as e:
            if e.code == PROTOCOL["wrong_pin"]:
                raise TVUnavailable("the PIN was wrong: ask for a new one and try again") from None
            raise
        out = unseal(field(text, "X_AuthResult") or "", key, hk, iv)
        app_id, keyword = field(out, "X_ApplicationId"), field(out, "X_Keyword")
        if not app_id or not keyword:
            raise TVUnavailable("the TV accepted the PIN but sent no keys")
        session_keys(keyword)   # refuses a key word that is not 16 bytes before it is kept
        tvbrands._keep(self.token_file, json.dumps({"app_id": app_id, "keyword": keyword}))
        self._challenge, self._enc = None, None
        return True

    # ---------- the TV ----------
    def is_on(self):
        """True when port 55000 answers, None when it does not. A Viera cannot be told apart in
        standby, and UNCONFIRMED: a set in networked standby may answer too."""
        s = socket.socket()
        s.settimeout(1.5)
        try:
            return True if s.connect_ex((self.ip, self.PORT)) == 0 else None
        except OSError:
            return None
        finally:
            s.close()

    def front(self):
        return None   # Panasonic does not say what is on screen

    def is_guest(self, front):
        return False

    def app_ids(self):
        """{tvctl app id: the TV's launch keyword} for the guest apps in the TV's own list, every 30 min."""
        at, found = self.found
        if found and time.time() - at < 1800:
            return found
        if self.is_on() is None:
            raise TVUnavailable("the TV is not answering")
        raw = field(self._soap("nrc", "X_GetAppList", "<X_AppType/><X_PackName/><X_AppMaker/>"), "X_AppList") or ""
        listed, found = [], {}
        for rec in raw.split(PROTOCOL["app_split"]):
            parts = [p.strip() for p in rec.split(PROTOCOL["app_field"])]
            i = next((n for n, p in enumerate(parts) if LAUNCH.match(p)), None)
            if i is None:
                continue
            title = next((p for p in parts[i + 1:] if p and not p.startswith(("http:", "https:"))), "")
            if not title or len(title) > 80:
                continue
            listed.append({"launch": parts[i], "name": title})
            aid = BY_NAME.get(tvbrands.plain(title))
            if aid:
                found.setdefault(aid, parts[i])
        if found:
            self.found = (time.time(), found)
            self.listed, self.listed_at = listed, time.time()
        return found

    def launch(self, tid):
        if not isinstance(tid, str) or not LAUNCH.match(tid):
            raise TVUnavailable("that is not an app keyword this TV lists")
        self._soap("nrc", "X_LaunchApp", "<X_AppType>%s</X_AppType><X_LaunchKeyword>%s</X_LaunchKeyword>"
                   % (PROTOCOL["app_type"], tid))

    def button(self, code):
        if not re.match(r"^NRC_[A-Z0-9_]{1,24}-ONOFF$", code or ""):
            raise TVUnavailable("not a Panasonic key")
        self._soap("nrc", "X_SendKey", "<X_KeyEvent>%s</X_KeyEvent>" % code)

    # ---------- volume and mute: the real level, over RenderingControl (never encrypted) ----------
    def _dmr(self, action, extra=""):
        return self._post("dmr", action, "<InstanceID>0</InstanceID><Channel>Master</Channel>" + extra)

    def volume_level(self):
        """The TV's real volume (0 to 100), or None when it does not say."""
        try:
            v = field(self._dmr("GetVolume"), "CurrentVolume")
        except TVUnavailable:
            return None
        return int(v) if v and v.strip().isdigit() else None

    def volume(self, up):
        level = self.volume_level()
        if level is None:   # the set does not say: the remote's own key
            return self.button(KEYS["volume_up" if up else "volume_down"])
        self._dmr("SetVolume", "<DesiredVolume>%d</DesiredVolume>" % max(0, min(100, level + (1 if up else -1))))

    def mute(self, on=None):
        try:
            v = field(self._dmr("GetMute"), "CurrentMute")
            if v is None or not v.strip().isdigit():
                raise TVUnavailable("no mute state")
            want = (v.strip() != "1") if on is None else bool(on)
            self._dmr("SetMute", "<DesiredMute>%d</DesiredMute>" % int(want))
        except TVUnavailable:
            if on is None:
                self.button(KEYS["mute"])

    # ---------- shows and guest-tv's welcome screen ----------
    def open_link(self, uri, app_id):
        """No deep link into a show is known on a Viera: the app opens on its own page."""
        self.quiet(40)
        if not app_id:
            raise TVUnavailable("a Panasonic TV only opens apps, not links: name the app")
        self.open_app(app_id)
        self.quiet(40)   # open_app set the shorter 20 s
        return "app"

    def _my_address(self):
        """This computer's address towards the TV (a UDP socket sends nothing when it connects)."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((self.ip, 9))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"
        finally:
            s.close()

    def open_page(self, url):
        """Open a web address in the TV's browser: launch the browser, give the TV an address of ours,
        and hand it the page when it connects (PROTOCOL, UNCONFIRMED on a real set)."""
        if not isinstance(url, str) or not re.match(r"^https?://[\x21-\x7e]+$", url):
            raise TVUnavailable("only a plain http or https address can be opened")
        data = url.encode("ascii")
        if len(data) > PROTOCOL["url_max"]:
            raise TVUnavailable("guest-tv's address is longer than %d characters: use a shorter computer name or home id"
                                % PROTOCOL["url_max"])
        me = self._my_address()
        srv = socket.socket()
        srv.bind((me, 0))   # only on the address the TV reaches
        srv.listen(1)
        srv.settimeout(PROTOCOL["connect_timeout"] + self.BROWSER_WAIT)
        done = {"ok": False}

        def serve():
            try:
                c, _ = srv.accept()
                with c:
                    c.sendall(PROTOCOL["url_head"] + bytes([len(data)]) + data + PROTOCOL["url_tail"])
                done["ok"] = True
            except OSError:
                pass

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        try:
            self._soap("nrc", "X_LaunchApp", "<X_AppType>%s</X_AppType><X_LaunchKeyword>%s</X_LaunchKeyword>"
                       % (PROTOCOL["app_type"], PROTOCOL["browser_keyword"]))
            time.sleep(self.BROWSER_WAIT)
            self._soap("nrc", "X_ConnectApp", "<X_ConnectKeyword>%s</X_ConnectKeyword><X_ConnectAddr>%s:%d</X_ConnectAddr>"
                       % (escape(PROTOCOL["connect_keyword"]), me, srv.getsockname()[1]))
            t.join(PROTOCOL["connect_timeout"])
        finally:
            srv.close()
        if not done["ok"]:
            raise TVUnavailable("the browser opened but the TV never came for the address (docs/PANASONIC.md)")

    def open_guest_app(self):
        if not self.page:
            raise TVUnavailable("guest-tv does not know its own address yet, so it cannot open its page on the TV")
        self.open_page(self.page)
