"""Philips TVs that are not Android: Titan OS ("titan") and older Linux sets with Saphi ("saphi").

Cut down from couch-tv's bridge/philips.py (github.com/Seagey/couch-tv) to what guest-tv uses.
NEW (Beta): checked against stand in TVs on the computer only (tools/philips_test.py). Philips does not
publish the newer parts of its network remote, so some of this is our best reading and the first real TV
will probably show something to fix. Everything not confirmed on a real TV is in PROTOCOL below, so a
tester's output can correct it in one place. docs/PHILIPS-TITAN.md and docs/PHILIPS-SAPHI.md say the rest.

JointSpace, Philips's own network remote:

  GET  system                  the TV's name, model and API version
  GET  powerstate              {"powerstate": "On"} or "Standby"
  POST input/key               {"key": "CursorUp"}: one remote button
  GET  audio/volume            {"current", "min", "max", "muted"}; POST the same to set
  GET  applications            the apps the TV lists; POST activities/launch with one of them
  GET  activities/current      the app in front (UNCONFIRMED on Titan OS)
  POST pair/request, pair/grant   pairing: the TV shows a PIN, the PIN goes back, signed

Titan OS: HTTPS on port 1926 with HTTP digest login (the TV's own self signed certificate, accepted for
this TV's address only). Pairing = a PIN. Philips signs the PIN with a key from its own TV Remote app: the
owner saves their own copy (python tv_philips.py secret) into data/philips-pair-secret.key. It is never in
this repository, never printed and never in an error message.

Saphi (about 2015 to 2019): plain port 1925 with no login is tried first, as couch-tv does. A set that
answers a read without a login needs no pairing (pairing is None). One that wants a login, or is silent on
1925, is tried on 1926 with the paired login (pairing is "pin").

Showing guest-tv: Titan OS has no way to replace its home and runs web pages only as Titan apps, so
guest-tv opens a Titan app labelled "Guest TV" when the TV lists one (a DevView sandbox app the owner
made, pointing at guest-tv's start page), and otherwise cannot show its welcome screen (the Guest remote
still works). A Saphi set that lists a "browser" activity gets guest-tv's page in its browser.
"""
import base64, getpass, hashlib, hmac, http.client, json, os, re, secrets, ssl, sys, threading, time
import urllib.error, urllib.request

import tvbrands, tvctl
from tvbrands import _Base, TVUnavailable, plain, _token_file, _read, _keep

PROTOCOL = {
    # Pairing. UNCONFIRMED on Titan OS: the field names and the signature recipe are our best reading
    # of how Philips's v6 pairing works, and the first tester settles them.
    "pair_scope": ["read", "write", "control"],
    "pair_ok": "SUCCESS",
    "app_id": "1",
    "sign": "hex-base64",     # base64 of the hex HMAC-SHA1 of timestamp + PIN, keyed with the shared key
    # What counts as "nothing in front": Philips's own home and live TV. UNCONFIRMED on Titan OS.
    "nothing": r"^$|^na$|launcher|(^|\.)home$|playtv|watchtv|^tv$",
    "input": r"hdmi|^ext\d*$|^av\d*$|scart",
    # Saphi. All UNCONFIRMED on a real Saphi TV.
    "open_probe": "audio/volume",           # a read Android sets guard with the login: answered without one = no pairing
    "browser_activity": "browser",          # listed in "system" (an "activities" list) when the TV has a browser
    "browser_open": "activities/browser",   # POST {"url": ...}: the browser opens that page
}

VERSIONS = ["6/", "5/", "1/", ""]   # tried in this order; the first one that answers "system" is kept
GUEST_LABEL = "Guest TV"            # a Titan app with this name is guest-tv's welcome screen
BROWSER_FRONT = "guesttv.browser"   # what "in front" is set to just after guest-tv's page was opened in the browser
SAFE_ID = re.compile(r"[A-Za-z0-9 ._:/+-]{1,120}")
SAFE_URL = re.compile(r"https?://[A-Za-z0-9.:\[\]_-]{1,100}(/[A-Za-z0-9._~/?&=%+-]{0,300})?")
PIN = re.compile(r"\d{4,6}")
SECRET_FILE = "philips-pair-secret.key"   # in data/ (git ignores data/*.key); the owner makes it

# Guest key name -> JointSpace key name (the names in Philips's JointSpace documentation).
KEYS = {"up": "CursorUp", "down": "CursorDown", "left": "CursorLeft", "right": "CursorRight",
        "ok": "Confirm", "back": "Back", "home": "Home", "play_pause": "PlayPause", "next": "Next",
        "previous": "Previous", "rewind": "Rewind", "fast_forward": "FastForward",
        "volume_up": "VolumeUp", "volume_down": "VolumeDown", "mute": "Mute"}

# The names Philips lists apps under, besides the names in tvctl.APPS (plain() of the name -> app id).
NAMES = {plain(a["name"]): a["id"] for a in tvctl.APPS}
NAMES.update({"amazonprimevideo": "prime-video", "primevideo": "prime-video", "appletv": "apple-tv",
              "appletvplus": "apple-tv", "iview": "abc-iview", "disneyplus": "disney-plus",
              "paramountplus": "paramount-plus", "kayosports": "kayo"})
BY_PACKAGE = {a["package"]: a["id"] for a in tvctl.APPS}


def secret_path():
    return os.path.join(tvbrands.DATA, SECRET_FILE)


def save_secret(text):
    """Keep the owner's own pairing key (base64) in data/, readable only by them."""
    text = (text or "").strip()
    try:
        base64.b64decode(text, validate=True)
    except Exception:
        raise ValueError("that does not look like the key (it should be base64 text)") from None
    if not text:
        raise ValueError("nothing to save")
    _keep(secret_path(), text)


def sign(secret, timestamp, pin):
    """The pairing signature. UNCONFIRMED recipe (PROTOCOL["sign"]): HMAC-SHA1 keyed with the shared
    key (as saved, base64), over the timestamp the TV sent followed by the PIN, as hex, then base64."""
    mac = hmac.new(base64.b64decode(secret), (str(timestamp) + str(pin)).encode(), hashlib.sha1).hexdigest()
    return base64.b64encode(mac.encode()).decode()


class PhilipsError(TVUnavailable):
    """The TV did not do what was asked, or answered with something unusable."""


class NeedsLogin(PhilipsError):
    """The TV answered 401: it is there, but wants the login pairing gives."""


class NotThere(PhilipsError):
    """The TV answered 404: this path is not on this TV (older sets have fewer)."""


def lists_browser(system, depth=0):
    """Whether "system" lists a browser activity: an "activities" list holding "browser", at any depth up
    to three (UNCONFIRMED on a Saphi TV)."""
    if not isinstance(system, dict) or depth > 3:
        return False
    for k, v in system.items():
        if k == "activities" and isinstance(v, list) and any(
                isinstance(x, str) and x.lower() == PROTOCOL["browser_activity"] for x in v):
            return True
        if isinstance(v, dict) and lists_browser(v, depth + 1):
            return True
    return False


class Digest:
    """HTTP digest login (RFC 7616, MD5, qop auth). The TV's challenge is kept and reused with a rising
    counter; a new one is taken when the TV asks again."""

    def __init__(self, user, password):
        self.user, self.password = user, password
        self.challenge = None
        self.count = 0

    def take(self, header):
        if not header or not header.lower().startswith("digest "):
            return False
        parts = dict((k.lower(), v.strip('"')) for k, v in re.findall(r'(\w+)=("[^"]*"|[^,\s]+)', header[7:]))
        if "nonce" not in parts:
            return False
        self.challenge, self.count = parts, 0
        return True

    def header(self, method, uri):
        c = self.challenge
        if not c:
            return None
        h = lambda s: hashlib.md5(s.encode()).hexdigest()
        self.count += 1
        nc, cnonce = "%08x" % self.count, secrets.token_hex(8)
        ha1 = h("%s:%s:%s" % (self.user, c.get("realm", ""), self.password))
        ha2 = h("%s:%s" % (method, uri))
        qop = "auth" if "auth" in (c.get("qop") or "").split(",") else None
        resp = h("%s:%s:%s:%s:auth:%s" % (ha1, c["nonce"], nc, cnonce, ha2)) if qop else h("%s:%s:%s" % (ha1, c["nonce"], ha2))
        out = 'Digest username="%s", realm="%s", nonce="%s", uri="%s", response="%s"' % (
            self.user, c.get("realm", ""), c["nonce"], uri, resp)
        if c.get("opaque"):
            out += ', opaque="%s"' % c["opaque"]
        if qop:
            out += ', qop=auth, nc=%s, cnonce="%s"' % (nc, cnonce)
        return out


class PhilipsTV(_Base):
    TAKES_KIND = True            # tvbrands.make builds it as PhilipsTV(ip, kind)
    KEYS = KEYS
    PORT_TLS, PORT_PLAIN = 1926, 1925   # the TV's ports (tools/philips_test.py moves them)
    SETTLE = 2.0                 # a Philips takes a moment after it comes on

    def __init__(self, ip, kind="titan"):
        super().__init__(ip)
        if kind not in ("titan", "saphi"):
            raise ValueError("kind is titan or saphi")
        self.kind = kind
        self._lock = threading.RLock()
        self.tls = kind == "titan"
        self.port = self.PORT_TLS if self.tls else self.PORT_PLAIN
        self.may_switch = kind == "saphi"   # a plain port that wants a login or is silent hands over to 1926
        self.version, self.system = None, {}
        self.open_api = None       # True: answers without a login, False: wants one, None: not known yet
        self.has_browser = False   # "system" lists a browser activity
        self.has_powerstate = True
        self.front_readable, self._front_at = None, 0.0
        self.visible = None        # what guest-tv last opened, used while the TV does not say what is in front
        self.applist = []          # [{"id", "label", "pkg", "entry"}], entry is the TV's own object
        self._list_at, self._list_read = 0.0, False
        self._auth = None
        self.last_error = None
        self.NOTHING = re.compile(PROTOCOL["nothing"], re.I)
        self.INPUT = re.compile(PROTOCOL["input"], re.I)
        self.store_file = _token_file(kind, ip)
        self._ctx = None

    # ---------- what is kept (data/, never in git) ----------
    def _stored(self):
        try:
            d = json.loads(_read(self.store_file) or "{}")
            return d if isinstance(d, dict) else {}
        except ValueError:
            return {}

    def _save(self, **changes):
        d = self._stored()
        d.update(changes)
        _keep(self.store_file, json.dumps({k: v for k, v in d.items() if v is not None}))

    @property
    def paired(self):
        s = self._stored()
        return bool(s.get("user") and s.get("password"))

    @property
    def pairing(self):
        """"pin" on Titan OS. On Saphi: None while the TV answers without a login, "pin" once it has asked for one."""
        if self.kind == "titan":
            return "pin"
        if self.open_api is None and self.version is None:
            try:
                self.find_version()
            except Exception:
                pass
        return "pin" if self.open_api is False or self.tls else None

    @property
    def can_open(self):
        """False once the TV is known to have no way to show guest-tv (no "Guest TV" app on Titan, no
        browser on Saphi). Until it has been asked, True."""
        if self.kind == "titan":
            return not (self._list_read and not self._guest_row())
        return not (self.version is not None and not self.has_browser)

    @property
    def sees_front(self):
        """False while the TV has just said it cannot tell what is in front (asked again after 5 minutes)."""
        return not (self.front_readable is False and time.time() - self._front_at < 300)

    # ---------- HTTP ----------
    def _ssl(self):
        """The TV's own certificate is self signed: accepted for this TV only (this context is passed on
        its requests and nowhere else)."""
        if not self.tls:
            return None
        if self._ctx is None:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self._ctx = ctx
        return self._ctx

    def _login(self):
        s = self._stored()
        if s.get("user") and s.get("password"):
            if not self._auth or self._auth.user != s["user"]:
                self._auth = Digest(s["user"], s["password"])
            return self._auth
        return None

    def _call(self, method, path, payload=None, auth=None, timeout=5, version=None, login=True):
        """One JointSpace request. auth: a Digest, else the kept login (when there is one). login=False
        sends none even when one is kept, so a 401 comes back as NeedsLogin."""
        with self._lock:
            if version is None and self.version is None:
                self.find_version()
            uri = "/" + (self.version if version is None else version or "") + path
            body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
            digest = auth or (self._login() if login else None)
            for attempt in range(2):
                headers = {"Content-Type": "application/json"} if body is not None else {}
                if digest and digest.challenge:
                    headers["Authorization"] = digest.header(method, uri)
                req = urllib.request.Request("%s://%s:%d%s" % ("https" if self.tls else "http", self.ip, self.port, uri),
                                             data=body, headers=headers, method=method)
                try:
                    try:
                        with urllib.request.urlopen(req, timeout=timeout, context=self._ssl()) as r:
                            status, text, head = r.status, r.read().decode("utf-8", "replace"), r.headers
                    except urllib.error.HTTPError as e:
                        status, text, head = e.code, e.read().decode("utf-8", "replace"), e.headers
                except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
                    raise TVUnavailable("the TV did not answer (%s)" % type(e).__name__) from None
                if status == 401 and digest and attempt == 0 and digest.take(head.get("WWW-Authenticate")):
                    continue
                if status == 401:
                    raise NeedsLogin("the TV wants a login: pair it first")
                if status == 404:
                    raise NotThere("the TV has no %s (it answered 404)" % path)
                if status >= 400:
                    raise PhilipsError("the TV answered %d to %s %s" % (status, method, path))
                if not text.strip():
                    return {}
                try:
                    return json.loads(text)
                except ValueError:
                    raise PhilipsError("the TV sent something that is not JSON for " + path) from None
            raise PhilipsError("the TV refused the login")

    def find_version(self):
        """The API version prefix this TV answers on (/6/, /5/, /1/ or none), from "system". On the plain
        port it also settles whether the TV wants a login at all (open_api). A Saphi TV whose plain port
        wants a login or is silent is tried on https 1926, the paired path; if that is silent too, the
        plain port is kept for the next try."""
        with self._lock:
            if self.version is not None:
                return self.version
            try:
                v = self._find_here()
                if self.tls or self._answers_without_login() or not self.may_switch:
                    return v
                why = NeedsLogin("the TV wants a login on port %d" % self.PORT_PLAIN)
            except (PhilipsError, TVUnavailable) as e:
                if not self.may_switch or self.tls:
                    raise
                why = e
            was = (self.version, self.system, self.has_browser)
            self.tls, self.port, self.version = True, self.PORT_TLS, None
            try:
                return self._find_here()
            except (PhilipsError, TVUnavailable):
                self.tls, self.port = False, self.PORT_PLAIN
                self.version, self.system, self.has_browser = was
                if self.version is not None:
                    return self.version   # 1926 is silent: the login goes over the plain port instead
                raise why from None

    def _find_here(self):
        for v in VERSIONS:
            try:
                data = self._call("GET", "system", version=v)
            except NeedsLogin:
                data = {"login": True}   # this version is there, it only wants a login
            except PhilipsError:
                continue
            if isinstance(data, dict) and data:
                self.version, self.system = v, ({} if data.get("login") else data)
                self.has_browser = lists_browser(self.system)
                return v
        raise PhilipsError("the TV did not answer \"system\" on any API version")

    def _answers_without_login(self):
        """Plain port only: one read that Android sets guard with the login (PROTOCOL["open_probe"]).
        Answered without one: this TV needs no pairing (Saphi). A 404 did not ask for a login either."""
        if self.tls:
            return False
        try:
            self._call("GET", PROTOCOL["open_probe"], login=False)
            self.open_api = True
        except NeedsLogin:
            self.open_api = False
        except NotThere:
            self.open_api = True
        except PhilipsError:
            self.open_api = None
        return bool(self.open_api)

    # ---------- pairing (a PIN) ----------
    def _device(self, device_id):
        return {"device_name": "guest-tv", "device_os": "guest-tv", "app_id": "app.guesttv",
                "app_name": "guest-tv", "type": "native", "id": device_id}

    def pair_start(self):
        """Ask the TV to show its PIN."""
        secret = _read(secret_path())
        if not secret:
            raise PhilipsError("no pairing key saved yet: run python tv_philips.py secret first (docs/PHILIPS-TITAN.md)")
        self.find_version()
        if self.open_api:
            raise PhilipsError("this TV answers without pairing, so there is nothing to pair (docs/PHILIPS-SAPHI.md)")
        device_id = secrets.token_hex(8)
        got = self._call("POST", "pair/request", {"scope": PROTOCOL["pair_scope"], "device": self._device(device_id)})
        if not isinstance(got, dict) or got.get("error_id") != PROTOCOL["pair_ok"] or not got.get("auth_key"):
            self.last_error = "the TV did not start pairing"
            raise PhilipsError("the TV did not start pairing (%s)" % ((got or {}).get("error_id") or "no answer"))
        self._save(pending=[device_id, str(got["auth_key"]), got.get("timestamp")])
        return True

    def pair_finish(self, pin):
        """Send the PIN back, signed, and keep the login the TV gave (data/, never in git)."""
        pin = str(pin or "").strip()
        if not PIN.fullmatch(pin):
            raise ValueError("the PIN is the 4 to 6 digits the TV shows")
        pending = self._stored().get("pending")
        if not (isinstance(pending, list) and len(pending) == 3):
            raise PhilipsError("ask the TV for a PIN first")
        secret = _read(secret_path())
        if not secret:
            raise PhilipsError("no pairing key saved: run python tv_philips.py secret first")
        device_id, auth_key, ts = pending
        grant = {"auth": {"auth_AppId": PROTOCOL["app_id"], "pin": pin, "auth_timestamp": ts,
                          "auth_signature": sign(secret, ts, pin)},
                 "device": self._device(device_id)}
        got = self._call("POST", "pair/grant", grant, auth=Digest(device_id, auth_key))
        if isinstance(got, dict) and got.get("error_id") not in (None, PROTOCOL["pair_ok"]):
            self.last_error = "the TV refused the PIN"
            raise PhilipsError("the TV refused the PIN (%s): ask for a new one and try again" % got.get("error_id"))
        self._save(user=device_id, password=auth_key, pending=None)
        self._auth, self.last_error, self._list_at = None, None, 0.0
        return True

    # ---------- reading the TV ----------
    def _read_power(self):
        if not self.has_powerstate:
            self._call("GET", "system")   # answers, so it is on
            return "On"
        try:
            data = self._call("GET", "powerstate")
        except NotThere:
            if not self.open_api:
                raise
            self.has_powerstate = False   # no powerstate on this TV: on while it answers
            return "On"
        p = data.get("powerstate") if isinstance(data, dict) else None
        return p if isinstance(p, str) and p else None

    def is_on(self):
        """True on, False in standby, None when it does not answer (off, gone, or not paired yet)."""
        try:
            p = self._read_power()
        except NeedsLogin:
            self.last_error = "the TV wants a login: pair it first"
            self.visible = None
            return None
        except TVUnavailable:
            self.visible = None
            return None
        if p != "On":
            self.visible = None
        return None if p is None else p == "On"

    def front(self):
        """The TV's id for what is on screen, or None (its home, live TV, an input, or the TV does not say)."""
        self._front_at = time.time()
        try:
            data = self._call("GET", "activities/current")
        except TVUnavailable:
            self.front_readable = False
            return self.visible   # what guest-tv opened, until the TV goes to standby
        self.front_readable = True
        comp = data.get("component") if isinstance(data, dict) and isinstance(data.get("component"), dict) else {}
        front = comp.get("packageName") or (data.get("id") if isinstance(data, dict) else "") or \
            (data.get("label") if isinstance(data, dict) else "") or ""
        if not isinstance(front, (str, int)) or not str(front) or self.NOTHING.search(str(front)):
            return None
        return str(front)

    def _applications(self, force=False):
        """The apps the TV lists, every 30 minutes (every 5 while it has listed none: older sets have no list)."""
        if not force and self._list_at and time.time() - self._list_at < (1800 if self.applist else 300):
            return self.applist
        try:
            data = self._call("GET", "applications")
        except NeedsLogin as e:
            raise TVUnavailable(str(e)) from None
        except NotThere:
            self.applist, self._list_at, self._list_read = [], time.time(), True
            return self.applist
        rows = data.get("applications") if isinstance(data, dict) else data
        listed = []
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict):
                continue
            comp = ((r.get("intent") or {}).get("component") or {}) if isinstance(r.get("intent"), dict) else {}
            aid = str(r.get("id") or comp.get("packageName") or "")
            label = str(r.get("label") or r.get("name") or "").strip()
            if not SAFE_ID.fullmatch(aid) or not label:
                continue   # an id that could carry anything else never goes back to the TV
            listed.append({"id": aid, "label": label, "pkg": comp.get("packageName") or "", "entry": r})
        self.applist, self._list_at, self._list_read = listed, time.time(), True
        return listed

    def _guest_row(self):
        return next((a for a in self.applist if plain(a["label"]) == plain(GUEST_LABEL)), None)

    def app_ids(self):
        """{tvctl app id: the TV's id} for the guest apps the TV lists, by package or by name, every 30 min."""
        at, found = self.found
        if found and time.time() - at < 1800:
            return found
        found = {}
        for r in self._applications():
            if plain(r["label"]) == plain(GUEST_LABEL):
                continue
            p = plain(r["label"])
            aid = BY_PACKAGE.get(r["pkg"]) or NAMES.get(p) or ("spotify" if p.startswith("spotify") else None)
            if aid and aid not in found:
                found[aid] = r["id"]
        if found:
            self.found = (time.time(), found)
        return found

    # ---------- doing things ----------
    def launch(self, tv_id):
        """Open an app the TV listed, sending back the TV's own object for it."""
        if not isinstance(tv_id, str) or not SAFE_ID.fullmatch(tv_id):
            raise TVUnavailable("not an app the TV listed")
        row = next((a for a in self._applications() if a["id"] == tv_id), None)
        if not row:
            raise TVUnavailable("not an app the TV listed")
        self._call("POST", "activities/launch", row["entry"], timeout=8)
        self.visible = row["id"]

    def button(self, code):
        if code not in KEYS.values():
            raise ValueError("not a key guest-tv sends")
        self._call("POST", "input/key", {"key": code})

    def volume(self, up):
        self.button("VolumeUp" if up else "VolumeDown")

    def mute(self, on=None):
        """A set over audio/volume when the TV answers it, else the remote's own Mute key (a toggle)."""
        try:
            v = self._call("GET", "audio/volume")
            if not isinstance(v, dict) or not isinstance(v.get("current"), int):
                raise PhilipsError("no volume")
            want = (not v.get("muted")) if on is None else bool(on)
            self._call("POST", "audio/volume", {"muted": want, "current": v["current"]})
        except NotThere:
            self.button("Mute")
        except PhilipsError:
            self.button("Mute")

    def key(self, name, times=1):
        if name == "home":
            self.quiet()
            try:
                return self.open_guest_app()
            except TVUnavailable:
                return self.button("Home")   # nothing of guest-tv's to open: the TV's own Home
        return super().key(name, times)

    def open_link(self, uri, app_id):
        """No deep link into a show is known on these TVs: the app opens on its own page."""
        self.open_app(app_id)
        self.quiet(40)   # after open_app, which sets the shorter quiet time
        return "app"

    def open_guest_app(self):
        if self.kind == "titan":
            self._applications()
            row = self._guest_row()
            if not row:
                raise TVUnavailable(
                    "this TV lists no app called \"%s\", so guest-tv's welcome screen cannot open on it: Titan OS only "
                    "runs web pages that are Titan apps (docs/PHILIPS-TITAN.md). The Guest remote still works" % GUEST_LABEL)
            self.launch(row["id"])
            return
        self.find_version()
        if not self.has_browser:
            raise TVUnavailable("this TV reports no browser to open guest-tv's page in, so its welcome screen cannot "
                                "open on it (docs/PHILIPS-SAPHI.md). The Guest remote still works")
        if not self.page or not SAFE_URL.fullmatch(self.page):
            raise TVUnavailable("guest-tv does not know its own address for this TV yet")
        self._call("POST", PROTOCOL["browser_open"], {"url": self.page}, timeout=8)
        self.visible = BROWSER_FRONT

    def is_guest(self, front):
        if not front:
            return False
        if self.kind == "titan":
            row = self._guest_row()
            return bool(row) and front in (row["id"], row["label"])
        return front == BROWSER_FRONT or PROTOCOL["browser_activity"] in front.lower()

    def nothing(self, front):
        if not self.can_open:
            return False   # no way to open guest-tv here, so the hook has nothing to do
        return front is None or bool(self.NOTHING.search(front) or self.INPUT.search(front))


# ---------------------------------------------------------------- tools/tv_app.py
SETUP = {
    "titan": [
        "Philips TVs on Titan OS only run web pages that are Titan apps, so the welcome screen needs a Titan app.",
        "Save your own pairing key once (it comes from Philips's own TV Remote app): python tv_philips.py secret",
        "Pair: TV_KIND=titan TV_IP=<tv address> .venv/bin/python tools/tv_app.py pair, then type the PIN the TV shows.",
        "For the welcome screen, make a Titan DevView sandbox app called Guest TV pointing at guest-tv's start page "
        "(tools/tv_app.py install prints the address). Without it the Guest remote still works.",
    ],
    "saphi": [
        "Many older Philips TVs need no pairing. Run: TV_KIND=saphi TV_IP=<tv address> .venv/bin/python tools/tv_app.py status",
        "If the TV lists a browser, guest-tv's page opens in it each time the TV comes on. If not, the Guest remote only.",
        "If the TV asks for a login, follow the Titan OS pairing steps (a PIN, and your own pairing key).",
    ],
}
BUILD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build")


def build(url, home_id):
    """The Titan start page with this computer's address and the home filled in, in build/titan/index.html,
    for hosting anywhere a Titan DevView app can point at (the computer serves its own copy too)."""
    if not re.fullmatch(r"https?://[\w.:-]+", url or "") or not re.fullmatch(r"[a-z0-9-]+", home_id or ""):
        raise SystemExit("bad --url or --home")
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tv-apps", "titan", "index.html")
    html = open(src).read()
    preset = 'var PRESET = {"guest": "%s", "home": "%s"};' % (url.split("://", 1)[1], home_id)
    out = os.path.join(BUILD, "titan", "index.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w").write(re.sub(r"var PRESET = \{[^}]*\};", lambda m: preset, html, count=1))
    return out


def install(ip, url, home_id):
    """Nothing can be put on a Titan TV from here (Titan's DevView app takes a page address from the
    owner's developer account), and a Saphi set has nothing to install. So this says what to do."""
    print("Titan OS: in your Titan Partner Portal sandbox, add an app called %s with this address:" % GUEST_LABEL)
    print("  %s/titan/?tv=%s" % (url, home_id))
    print("Then pair the TV to the sandbox with the code DevView shows. Saphi sets: nothing to install.")


def uninstall(ip):
    print("Remove the Guest TV app from your Titan Partner Portal sandbox. Nothing else was put on the TV.")
    print('To stop the computer opening guest-tv, set "tv_hook": false in data/settings.json and restart server.py.')


if __name__ == "__main__":
    if sys.argv[1:] == ["secret"]:
        print("Paste your own Philips pairing key (from your copy of Philips's TV Remote app). Nothing is shown as you type.")
        save_secret(getpass.getpass("key: "))
        print("Saved in data/%s (readable only by you, never in git)." % SECRET_FILE)
    else:
        print("python tv_philips.py secret   saves your own pairing key")
