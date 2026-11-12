"""VIZIO TVs (SmartCast and VIZIO OS) for guest-tv: the Guest remote and the guest agent, with no welcome
screen on the TV. Set "tv_kind": "vizio" next to the TV's address.

NEW (BETA). Checked against a stand in TV on the computer only (tools/vizio_test.py, docs/VIZIO.md).
Not one line of this has been seen from a real VIZIO yet: first reports from real TVs are wanted. Cut down
from couch-tv's bridge/vizio.py (github.com/Seagey/couch-tv), keeping its honesty about what is confirmed.

How a VIZIO is reached: the SmartCast API, JSON over HTTPS on port 7345 (firmware 4.0 and newer, and
VIZIO OS) or 9000 (older firmware), with the TV's own self signed certificate (accepted for this TV's
address only, never anywhere else). The TV shows a 4 digit PIN once; the token it hands back goes in an
AUTH header on every later request and is kept in data/ (0600, git ignored), never logged or printed.

  PUT  /pairing/start             the TV shows a PIN
  PUT  /pairing/pair              the PIN goes back, the token comes back
  GET  /state/device/power_mode   1 on, 0 standby
  PUT  /key_command/              a remote button, as a codeset and a code
  PUT  /app/launch                open an app, by its name space and id
  GET  /app/current               the app in front

"documented" below means two public references agree (the open pyvizio library's constants and the
community Vizio_SmartCast_API notes). UNCONFIRMED means one source or our own reading.

THE WELCOME SCREEN: it cannot open on a VIZIO. VIZIO OS has no browser, takes no sideloaded app, and its
app programme is a closed partner scheme; its built in Chromecast only opens registered receivers. So
can_open is False, open_guest_app() says so, and the hook does nothing. The Guest remote's Home button
presses VIZIO's own Home. Everything on the phone (Guest remote, agent, aircon, lights, house guide) works.

What it cannot do: the welcome screen on the TV, the Guest profile picker, typing, deep links into a show
(Netflix and YouTube open on their own page), Spotify search (Spotify just opens), screenshots.
"""
import json, re, secrets, ssl, time, urllib.error, urllib.request

import tvbrands, tvctl
from tvbrands import TVUnavailable

SETUP = [
    "Set the TV's power mode to Quick Start (not Eco) if you want the Guest remote to turn the TV on.",
    "Run: TV_KIND=vizio TV_IP=<tv address> .venv/bin/python tools/tv_app.py pair  (the TV shows a 4 digit PIN, type it in).",
    "There is no TV side app: a VIZIO cannot show guest-tv's welcome screen. The Guest remote on the phone is what works.",
]

# Request shapes in one place, so a tester's report can correct them here.
POWER = "/state/device/power_mode"      # documented path; 1 on, 0 standby is UNCONFIRMED (pyvizio reads it so)
PAIR_START = "/pairing/start"           # documented
PAIR_FINISH = "/pairing/pair"           # documented
KEY = "/key_command/"                   # documented: {"KEYLIST": [{"CODESET": n, "CODE": n, "ACTION": "KEYPRESS"}]}
LAUNCH = "/app/launch"                  # documented: {"VALUE": {"NAME_SPACE": n, "APP_ID": "s", "MESSAGE": null}}
CURRENT = "/app/current"                # UNCONFIRMED (pyvizio only): ITEM.VALUE {"NAME_SPACE", "APP_ID", ...}
OK = {"SUCCESS"}                        # documented: the answer is in STATUS.RESULT, HTTP codes are not reliable
NEEDS_PAIRING = {"REQUIRES_PAIRING", "REQUIRES_SYSTEM_PIN"}   # UNCONFIRMED which one a bad token gets
PIN_WRONG = {"PAIRING_DENIED", "CHALLENGE_INCORRECT", "VALUE_OUT_OF_RANGE"}
PIN_LOCKED = {"MAX_CHALLENGES_EXCEEDED"}
BUSY = {"BLOCKED", "BUSY"}
HOME_APP = (4, "1")                     # UNCONFIRMED: what /app/current says on VIZIO's own home

# Guest key name -> (CODESET, CODE). From pyvizio's TV key table (one public source), so UNCONFIRMED on a
# real set except volume and power, which the community notes also list. "play_pause" is worked out in
# button(): VIZIO has separate play and pause keys.
VIZIO_KEYS = {
    "up": (3, 8), "down": (3, 0), "left": (3, 1), "right": (3, 7), "ok": (3, 2), "back": (4, 0),
    "play_pause": "play_pause", "next": (2, 0), "previous": (2, 1), "rewind": (2, 1), "fast_forward": (2, 0),
    "volume_up": (5, 1), "volume_down": (5, 0), "mute": (5, 4),
}
PLAY, PAUSE = (2, 3), (2, 2)
VIZIO_HOME = (4, 15)                    # VIZIO's own Home key
MUTE_ON, MUTE_OFF = (5, 3), (5, 2)

# tvctl app id -> (NAME_SPACE, APP_ID), from VIZIO's own public app list (scfs.vizio.com/appservice, read
# 12 Nov 2026, the "*" chipset entry; the same as couch-tv's table). None launched on a real set yet.
# VIZIO sells in the US, Canada and Mexico, so Stan, Binge, iview and the rest are not on its list.
APPS = {
    "netflix": (3, "1"), "youtube": (5, "1"), "prime-video": (2, "4"), "disney-plus": (2, "75"),
    "paramount-plus": (2, "37"), "apple-tv": (3, "4"),
}
EQUIVALENT = {2: 4, 4: 2}               # name spaces 2 and 4 name the same apps (pyvizio, UNCONFIRMED)

SAFE_APP = re.compile(r"^vizio\.(\d{1,2})\.([A-Za-z0-9]{1,16})$")   # "vizio.<name space>.<app id>"
PIN = re.compile(r"^\d{4}$")
SAFE_DEVICE = re.compile(r"^[A-Za-z0-9._-]{4,64}$")


def _status(data):
    st = data.get("STATUS") if isinstance(data, dict) else None
    r = st.get("RESULT") if isinstance(st, dict) else None
    return str(r).upper() if r is not None else ""


class VizioTV(tvbrands._Base):
    kind = "vizio"
    KEYS = VIZIO_KEYS
    can_open = False       # no browser, no sideloading: guest-tv's welcome screen cannot open
    sees_front = True      # /app/current, where the TV answers it
    pairing = "pin"
    PORTS = [7345, 9000]   # 7345 on firmware 4.0 and newer and VIZIO OS, 9000 before (documented)
    TLS = True             # the TV's self signed certificate; only the stand in test turns this off

    def __init__(self, ip):
        super().__init__(ip)
        self.token_file = tvbrands._token_file("vizio", ip)
        self.port = None
        self._played = False
        self.last_error = None

    # ---------- what is kept (data/, 0600): the device id, the token, a pairing in progress ----------
    def _stored(self):
        try:
            d = json.loads(tvbrands._read(self.token_file) or "{}")
            return d if isinstance(d, dict) else {}
        except ValueError:
            return {}

    def _save(self, **changes):
        d = {k: v for k, v in (self._stored() | changes).items() if v is not None}
        tvbrands._keep(self.token_file, json.dumps(d))

    def _device_id(self):
        did = self._stored().get("device_id")
        if not (isinstance(did, str) and SAFE_DEVICE.match(did)):
            did = "guesttv-" + secrets.token_hex(6)
            self._save(device_id=did)
        return did

    def _token(self):
        t = self._stored().get("token")
        return t if isinstance(t, str) and t else None

    # ---------- HTTPS ----------
    def _ssl(self):
        """The TV's certificate is its own, self signed, issued to a VIZIO name rather than this address.
        It is accepted for this TV only: this context goes on this TV's requests and nowhere else."""
        if not self.TLS:
            return None
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _raw(self, method, path, payload, auth, port, timeout):
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        headers = {"Content-Type": "application/json"} if body is not None else {}
        tok = self._token() if auth else None
        if tok:
            headers["AUTH"] = tok
        req = urllib.request.Request("%s://%s:%d%s" % ("https" if self.TLS else "http", self.ip, port, path),
                                     data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self._ssl()) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:   # the TV says "requires pairing" with a 403 and a JSON body
            return e.code, e.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError, ssl.SSLError, ValueError) as e:
            raise TVUnavailable("the TV did not answer (%s)" % type(e).__name__) from None

    def _call(self, method, path, payload=None, auth=True, timeout=4, port=None):
        """One SmartCast request, judged by STATUS.RESULT. Returns the JSON; raises TVUnavailable."""
        if port is None:
            port = self.find_port()
        status, text = self._raw(method, path, payload, auth, port, timeout)
        try:
            data = json.loads(text) if text.strip() else {}
        except ValueError:
            data = None
        result = _status(data)
        if result in NEEDS_PAIRING or (status in (401, 403) and data is not None and result not in OK):
            raise TVUnavailable("the TV wants pairing first: run tools/tv_app.py pair (docs/VIZIO.md)" if not self._token()
                                else "the TV no longer accepts the kept token: pair again (docs/VIZIO.md)")
        if data is None:
            raise TVUnavailable("the TV sent something that is not JSON for %s (HTTP %s)" % (path, status))
        if result and result not in OK:
            raise TVUnavailable("the TV answered %s to %s" % (result.lower(), path))
        if status >= 400 and not result:
            raise TVUnavailable("the TV answered HTTP %s to %s" % (status, path))
        return data

    def find_port(self):
        """The first port that answers like a SmartCast TV (any STATUS, even "requires pairing")."""
        if self.port is not None:
            return self.port
        last = "no port tried"
        for p in self.PORTS:
            try:
                self._call("GET", POWER, port=p, timeout=3)
            except TVUnavailable as e:
                if "wants pairing" in str(e) or "no longer accepts" in str(e):
                    pass                      # it is a SmartCast TV, it only wants the token
                elif "not JSON" in str(e):
                    last = "port %d answers, but not like a VIZIO" % p
                    continue
                else:
                    last = "port %d: %s" % (p, e)
                    continue
            self.port = p
            return p
        raise TVUnavailable("no SmartCast answer on port %s (%s)" % (" or ".join(map(str, self.PORTS)), last))

    # ---------- pairing (the PIN on the TV) ----------
    def pair_start(self):
        """Ask the TV to show its 4 digit PIN. What pair_finish needs is kept, so the PIN can come from
        another run."""
        try:
            got = self._call("PUT", PAIR_START, {"DEVICE_NAME": "guest-tv", "DEVICE_ID": self._device_id()}, auth=False)
        except TVUnavailable as e:
            if any(b.lower() in str(e) for b in BUSY):
                raise TVUnavailable("the TV is already showing a PIN for something else: press Back on the TV, "
                                    "wait a minute and try again") from None
            raise
        item = got.get("ITEM") if isinstance(got, dict) else None
        if not isinstance(item, dict) or item.get("PAIRING_REQ_TOKEN") is None:
            raise TVUnavailable("the TV did not start pairing (no pairing request came back)")
        self._save(pending={"req": item.get("PAIRING_REQ_TOKEN"), "challenge": item.get("CHALLENGE_TYPE", 1)})
        return True

    def pair_finish(self, pin):
        """Send the PIN, keep the token the TV gives back. The PIN and the token are never in an error."""
        pin = str(pin or "").strip()
        if not PIN.match(pin):
            raise TVUnavailable("the PIN is the 4 digits the TV shows")
        pending = self._stored().get("pending")
        if not isinstance(pending, dict) or pending.get("req") is None:
            raise TVUnavailable("ask the TV for a PIN first")
        body = {"DEVICE_ID": self._device_id(), "CHALLENGE_TYPE": pending.get("challenge", 1),
                "RESPONSE_VALUE": pin, "PAIRING_REQ_TOKEN": pending["req"]}
        try:
            got = self._call("PUT", PAIR_FINISH, body, auth=False)
        except TVUnavailable as e:
            text = str(e)
            if any(w.lower() in text for w in PIN_WRONG):
                self._save(pending=None)
                raise TVUnavailable("the TV refused the PIN: ask for a new one and try again") from None
            if any(w.lower() in text for w in PIN_LOCKED):
                self._save(pending=None)
                raise TVUnavailable("too many wrong PINs: wait a few minutes before asking for a new one") from None
            raise
        item = got.get("ITEM") if isinstance(got, dict) else None
        token = item.get("AUTH_TOKEN") if isinstance(item, dict) else None
        if not isinstance(token, str) or not token:
            raise TVUnavailable("the TV accepted the PIN but sent no token")
        self._save(token=token, pending=None)
        return True

    # ---------- reading the TV ----------
    def is_on(self):
        """True on, False in standby, None when it does not answer (or does not know this computer yet)."""
        try:
            data = self._call("GET", POWER, timeout=2)
        except TVUnavailable as e:
            self.last_error = str(e)
            return None
        items = data.get("ITEMS") if isinstance(data, dict) else None
        v = items[0].get("VALUE") if isinstance(items, list) and items and isinstance(items[0], dict) else None
        if isinstance(v, bool) or not isinstance(v, int):
            return None
        self.last_error = None
        return v == 1

    def _front_pair(self):
        """(name space, app id) in front, () for none, None when the TV does not say."""
        try:
            data = self._call("GET", CURRENT)
        except TVUnavailable:
            return None
        item = data.get("ITEM") if isinstance(data, dict) else None
        v = item.get("VALUE") if isinstance(item, dict) else None
        if not isinstance(v, dict) or v.get("APP_ID") in (None, ""):
            return ()
        try:
            return int(v.get("NAME_SPACE")), str(v["APP_ID"])
        except (TypeError, ValueError):
            return ()

    def front(self):
        """"vizio.<name space>.<app id>" of the app on screen, written as in the APPS table, or None for
        nothing, VIZIO's own home, an input, or a TV that does not say."""
        pair = self._front_pair()
        if not pair or pair == HOME_APP:
            return None
        ns, aid = pair
        for entry in APPS.values():
            if entry[1] == aid and (entry[0] == ns or EQUIVALENT.get(entry[0]) == ns):
                return "vizio.%d.%s" % entry
        return "vizio.%d.%s" % (ns, aid)

    def app_ids(self):
        """VIZIO keeps its app list in its cloud, not on the TV, so this is the fixed table above for the
        apps guest-tv knows, cached 30 min. It raises when the TV does not answer."""
        at, found = self.found
        if found and time.time() - at < 1800:
            return found
        if self.is_on() is None:
            raise TVUnavailable(self.last_error or "the TV is not answering")
        found = {a: "vizio.%d.%s" % e for a, e in APPS.items() if a in tvctl.BY_ID}
        self.found = (time.time(), found)
        return found

    def guest_id(self):
        return None   # guest-tv is never on screen on a VIZIO

    def nothing(self, front):
        return front is None

    # ---------- doing things ----------
    def launch(self, tid):
        m = SAFE_APP.match(tid or "")
        if not m:
            raise TVUnavailable("not an app id this driver sends")
        self._call("PUT", LAUNCH, {"VALUE": {"NAME_SPACE": int(m.group(1)), "APP_ID": m.group(2), "MESSAGE": None}}, timeout=8)

    def _press(self, code):
        self._call("PUT", KEY, {"KEYLIST": [{"CODESET": code[0], "CODE": code[1], "ACTION": "KEYPRESS"}]})

    def button(self, code):
        if code == "play_pause":   # separate play and pause keys: press the one the last press was not
            code = PAUSE if self._played else PLAY
            self._played = not self._played
        if not (isinstance(code, tuple) and len(code) == 2):
            raise TVUnavailable("not a key this driver sends")
        self._press(code)

    def key(self, name, times=1):
        if name == "home":   # guest-tv's welcome cannot open here: VIZIO's own Home
            self.quiet()
            return self.button(VIZIO_HOME)
        return super().key(name, times)

    def volume(self, up):
        self._press(VIZIO_KEYS["volume_up" if up else "volume_down"])

    def mute(self, on=None):
        self._press(MUTE_ON if on is True else MUTE_OFF if on is False else VIZIO_KEYS["mute"])

    def open_link(self, uri, app_id):
        """No deep link into a show is known on a VIZIO: the app opens on its own page ("app")."""
        self.quiet(40)
        if not app_id:
            raise TVUnavailable("VIZIO TVs only open apps, not links")
        self.open_app(app_id)
        self.quiet(40)   # open_app set the shorter 20 seconds
        return "app"

    def open_guest_app(self):
        raise TVUnavailable("guest-tv's welcome screen cannot open on a VIZIO: VIZIO OS has no browser and takes "
                            "no outside apps. The Guest remote on the phone works")
