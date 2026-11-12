"""guest-tv on a Roku (a Roku TV, or a Roku stick or box): "tv_kind": "roku".

Cut down from couch-tv's bridge/roku.py (github.com/Seagey/couch-tv) to what guest-tv uses, and made
sync like the rest of guest-tv. Built from Roku's External Control Protocol (ECP) documentation and
checked against a stand-in Roku on the computer (tools/roku_test.py), NOT yet on a real Roku
(docs/ROKU.md). ECP is plain HTTP on port 8060 on the home Wi-Fi, with no pairing and no key:

- GET  query/device-info      power-mode (PowerOn when the TV is on)
- GET  query/active-app       the app in front (no id on Roku's own home)
- GET  query/apps             every channel installed, with its id and name
- POST keypress/<Key>         a remote button
- POST launch/<id>[?contentId=&mediaType=]   open a channel, and a title in it where the channel allows

guest-tv's welcome screen is guest-tv's own Roku channel (tv-apps/roku), sideloaded through Roku's
Developer Mode. A sideloaded channel is always "dev" on a Roku, and a Roku holds one. Roku channels are
not web pages, so the channel draws the welcome screen itself from GET /api/tv/native on the computer.
It is a channel the computer opens each time the TV comes on, not a true home screen: the remote's Home
button still opens Roku's home.

"Control by mobile apps" (Settings, System, Advanced system settings): newer Roku OS limits ECP unless
it allows network access, and a Roku that is limiting it answers keypress and launch with 403. That is
said plainly (LIMITED_HELP) instead of looking like a dead TV.

What a Roku cannot do here: the Guest profile picker (no way to read the screen), Spotify search
(Spotify just opens), a volume level or mute state, screenshots.
"""
import getpass, io, json, os, re, socket, time, urllib.error, urllib.parse, urllib.request, uuid, zipfile
import xml.etree.ElementTree as ET

import tvbrands, tvctl
from tvbrands import TVUnavailable

HERE = os.path.dirname(os.path.abspath(__file__))
CHANNEL = os.path.join(HERE, "tv-apps", "roku")
BUILD = os.path.join(HERE, "build")
ZIP = os.path.join(BUILD, "guest-tv-roku.zip")
SIZE_LIMIT = 4 * 1024 * 1024   # Roku's documented size for a channel package

GUEST_APP = "dev"   # a sideloaded channel is always "dev"

# What power-mode says. Only PowerOn is documented (developer.roku.com, query/device-info); the other
# values (Ready, DisplayOff, Headless) come from community write-ups, so anything but PowerOn is off.
ON_MODE = "PowerOn"

# What is "in front" when no app is: Roku's home and screensavers have no id (""), live TV and inputs on
# a Roku TV are "tvinput.*". Neither is checked on a real Roku.
NOTHING = re.compile(r"^$|^tvinput\.", re.I)
SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,40}")

# Roku channel ids for the guest apps, from couch-tv's bridge/apps.py (ROKU). Only Netflix 12, YouTube
# 837 and Prime Video 13 were confirmed from pages that were read; the rest are UNVERIFIED (channel store
# addresses, community lists). An id is only used when the Roku's own list (query/apps) has it, and
# otherwise an app is found by the name the Roku lists it under, so a wrong id cannot open a wrong app.
# Stan, Binge, the Australian free to air apps and Kayo have no known id and are found by name only.
ROKU = {
    "netflix": {"ids": ["12"]},
    "youtube": {"ids": ["837"]},
    "prime-video": {"ids": ["13"], "names": ["Amazon Prime Video", "Prime Video"]},
    "disney-plus": {"ids": ["291097"], "names": ["Disney+", "Disney Plus"]},
    "paramount-plus": {"ids": ["31440"], "names": ["Paramount+", "Paramount Plus"]},
    "apple-tv": {"ids": ["551012"], "names": ["Apple TV", "Apple TV+"]},
    "spotify": {"ids": ["22297"]},
    "stan": {"names": ["Stan"]},
    "binge": {"names": ["BINGE", "Binge"]},
    "abc-iview": {"names": ["ABC iview", "iview"]},
    "sbs-on-demand": {"names": ["SBS On Demand"]},
    "9now": {"names": ["9Now"]},
    "7plus": {"names": ["7plus"]},
    "10play": {"names": ["10", "10 play", "10play"]},
    "kayo": {"names": ["Kayo Sports", "Kayo"]},
}
BY_ROKU_ID = {rid: aid for aid, r in ROKU.items() for rid in r.get("ids", [])}
BY_NAME = {}
for _a in tvctl.APPS:
    for _n in [_a["name"]] + ROKU.get(_a["id"], {}).get("names", []):
        BY_NAME.setdefault(tvbrands.plain(_n), _a["id"])

# Guest key name -> ECP key (developer.roku.com, External Control API). Roku has one Play/Pause key.
# Volume keys only do anything on a Roku TV, not on a stick or box.
ROKU_KEYS = {"up": "Up", "down": "Down", "left": "Left", "right": "Right", "ok": "Select", "back": "Back",
             "play_pause": "Play", "next": "Fwd", "previous": "Rev", "rewind": "Rev", "fast_forward": "Fwd",
             "volume_up": "VolumeUp", "volume_down": "VolumeDown", "mute": "VolumeMute"}

LIMITED_HELP = ("the Roku is refusing remote control (Control by mobile apps is on a limited mode). On the Roku open "
                "Settings, System, Advanced system settings, Control by mobile apps, Network access, and choose "
                "Permissive (older Roku OS) or Enabled (newer). The names differ by Roku OS version.")

SETUP = """Roku (a Roku TV, or a Roku stick or box), once:
1. Developer Mode: on the Roku remote press Home three times, Up twice, Right, Left, Right, Left, Right.
   Choose Enable installer and restart, accept the licence and make a developer password (no Roku account).
2. Settings, System, Advanced system settings, Control by mobile apps, Network access: Permissive
   (older Roku OS) or Enabled (newer).
3. TV_KIND=roku TV_IP=<tv address> .venv/bin/python tools/tv_app.py install   (asks for the developer password,
   or reads ROKU_DEV_PASSWORD; it is never kept). No pairing. Then: tools/tv_app.py open.
A Roku holds one sideloaded channel: installing guest-tv replaces any other one (couch-tv's, for example)."""


class ECPLimited(TVUnavailable):
    """The Roku answered 403: Control by mobile apps is limiting it."""


class RokuTV(tvbrands._Base):
    kind = "roku"
    KEYS = ROKU_KEYS
    pairing = None          # ECP has no pairing and no key
    PORT = 8060             # ECP (tools/roku_test.py moves it)
    DEV_PORT = 80           # the developer installer, for install and uninstall

    def __init__(self, ip):
        super().__init__(ip)
        self.ecp_limited = False   # the last command was refused with 403

    # ---------- ECP ----------
    def _ecp(self, method, path, timeout=4):
        """One ECP request: the body as text. 403 means Control by mobile apps is limiting the Roku."""
        url = "http://%s:%d/%s" % (self.ip, self.PORT, path)
        try:
            code, body = tvbrands._http(method, url, "" if method == "POST" else None, timeout=timeout)
        except (urllib.error.URLError, OSError, socket.timeout) as e:
            raise TVUnavailable("the Roku did not answer (%s)" % type(e).__name__) from None
        if code == 403:
            if method == "POST":
                self.ecp_limited = True
                self.note("Roku refused a command: Control by mobile apps is limiting it")
            raise ECPLimited(LIMITED_HELP)
        if code >= 400:
            raise TVUnavailable("the Roku answered %s to %s %s" % (code, method, path.split("?")[0]))
        if method == "POST":
            self.ecp_limited = False
        return body

    def _xml(self, path, timeout=4):
        try:
            return ET.fromstring(self._ecp("GET", path, timeout))
        except ET.ParseError:
            raise TVUnavailable("the Roku sent something that is not XML for %s" % path) from None

    def ecp_status(self):
        """Whether Control by mobile apps is limiting the Roku, in a plain sentence (for a status page)."""
        return {"limited": self.ecp_limited, "message": LIMITED_HELP if self.ecp_limited else None}

    # ---------- reading the TV ----------
    def is_on(self):
        """True on, False in standby, None when it does not answer. device-info is allowed under every
        setting of Control by mobile apps, so a limiting Roku still reads as on or off."""
        try:
            root = self._xml("query/device-info", 2)
        except TVUnavailable:
            return None
        return ((root.findtext("power-mode") or "").strip() or ON_MODE) == ON_MODE   # a Roku that does not say is on

    def front(self):
        """The id of the channel in front, "" for Roku's home (and screensavers), "tvinput.*" for live TV
        or an input, None when it cannot be read."""
        try:
            app = self._xml("query/active-app", 3).find("app")
        except TVUnavailable:
            return None
        rid = (app.get("id") or "") if app is not None else ""
        return rid if rid == "" or SAFE_ID.fullmatch(rid) else None

    def guest_id(self):
        return GUEST_APP

    def nothing(self, front):
        """Roku's home, a screensaver, live TV or an input. Unreadable (None) is not nothing: left alone,
        as couch-tv does."""
        return front is not None and bool(NOTHING.match(front))

    def app_ids(self):
        """The guest apps on the Roku, by id or by the name it lists them under, every 30 min."""
        at, found = self.found
        if found and time.time() - at < 1800:
            return found
        root = self._xml("query/apps")
        found = {}
        for el in root.findall("app"):
            rid, title = el.get("id") or "", (el.text or "").strip()
            if not SAFE_ID.fullmatch(rid) or rid == GUEST_APP:
                continue   # never send an id back that is not a plain id; never offer guest-tv as an app
            aid = BY_ROKU_ID.get(rid) or BY_NAME.get(tvbrands.plain(title))
            if aid and aid not in found:
                found[aid] = rid
        if found:
            self.found = (time.time(), found)
        return found

    # ---------- doing things ----------
    def launch(self, rid, content_id=None, media_type=None, params=None):
        if not SAFE_ID.fullmatch(str(rid)):
            raise TVUnavailable("not a Roku channel id")
        q = {}
        if content_id:
            q["contentId"] = str(content_id)
            if media_type:
                q["mediaType"] = media_type
        q.update(params or {})
        self._ecp("POST", "launch/%s%s" % (rid, ("?" + urllib.parse.urlencode(q)) if q else ""), timeout=8)

    def button(self, code):
        if code not in ROKU_KEYS.values():
            raise KeyError(code)
        self._ecp("POST", "keypress/" + code)
        time.sleep(0.1)

    def volume(self, up):
        self.button("VolumeUp" if up else "VolumeDown")

    def mute(self, on=None):
        """A toggle: ECP has VolumeMute but reports no mute state, so "on" cannot be honoured exactly.
        Only a Roku TV (not a stick or box) has a volume to mute."""
        self.button("VolumeMute")

    def open_link(self, uri, app_id):
        """Netflix and YouTube open the title with ECP's deep link (contentId, mediaType), as couch-tv
        does; UNVERIFIED on a real Roku. Every other app just opens. Only the id from
        tvbrands.netflix_id or youtube_id goes to the TV, never the guest's text."""
        self.quiet(40)
        nid, yid = tvbrands.netflix_id(uri), tvbrands.youtube_id(uri)
        rid = self.app_ids().get(app_id)
        try:
            if rid and app_id == "netflix" and nid:
                self.launch(rid, content_id=nid, media_type="series")
                return "show"
            if rid and app_id == "youtube" and yid:
                self.launch(rid, content_id=yid, media_type="live")
                return "show"
        except ECPLimited:
            raise
        except TVUnavailable:
            pass
        self.open_app(app_id)
        return "app"

    def home_id(self):
        """The home in self.page (http://<computer>:5410/tv/?tv=<home>&brand=roku), or None."""
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.page or "").query)
        home = (q.get("tv") or [""])[0]
        return home if re.fullmatch(r"[a-z0-9-]{1,40}", home) else None

    def open_guest_app(self):
        """Launch guest-tv's sideloaded channel. The home goes along as a launch parameter (the channel
        uses the one baked in when there is none). If guest-tv's channel is not installed, the Roku
        answers launch/dev with an error and that is said plainly."""
        home = self.home_id()
        try:
            self.launch(GUEST_APP, params={"home": home} if home else None)
        except ECPLimited:
            raise
        except TVUnavailable as e:
            if "answered" in str(e):
                raise TVUnavailable("guest-tv's Roku channel is not on this Roku (tools/tv_app.py install), "
                                    "or another sideloaded channel replaced it") from None
            raise


# ---------------------------------------------------------------- the channel: build, install, uninstall

def build(url, home_id):
    """Pack tv-apps/roku into build/guest-tv-roku.zip, with config.json saying where the computer is and
    which home to show. No password and no key goes in it."""
    url = (url or "").rstrip("/")
    if not re.fullmatch(r"https?://[\w.:-]+", url) or not re.fullmatch(r"[a-z0-9-]{1,40}", home_id or ""):
        raise SystemExit("bad --url or --home")
    if re.sub(r"^https?://", "", url).split(":")[0].endswith(".local"):
        print("note: a .local name may not resolve on a Roku. Use the computer's number address.")
    os.makedirs(BUILD, exist_ok=True)
    entries = {}
    for dirpath, dirnames, names in os.walk(CHANNEL):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for n in sorted(names):
            if not n.startswith("."):
                full = os.path.join(dirpath, n)
                entries[os.path.relpath(full, CHANNEL).replace(os.sep, "/")] = full
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(entries.pop("manifest"), "manifest")   # first, as Roku's own tools do
        for name, full in entries.items():
            z.write(full, name)
        z.writestr("config.json", json.dumps({"url": url, "home": home_id}) + "\n")
    if os.path.getsize(ZIP) > SIZE_LIMIT:
        print("warning: the channel is over 4 MB. Roku may refuse it.")
    return ZIP


def _multipart(fields, filename, data):
    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    for k, v in fields.items():
        body.write(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, k, v)).encode())
    body.write(('--%s\r\nContent-Disposition: form-data; name="archive"; filename="%s"\r\n'
                "Content-Type: application/x-zip-compressed\r\n\r\n" % (boundary, filename)).encode())
    body.write(data)
    body.write(("\r\n--%s--\r\n" % boundary).encode())
    return body.getvalue(), "multipart/form-data; boundary=" + boundary


def _password():
    return os.environ.get("ROKU_DEV_PASSWORD") or getpass.getpass("Roku developer password (user rokudev): ")


def _installer(ip, submit, zip_path=None, password=None):
    """Roku's developer installer (port 80, HTTP digest sign in as rokudev). Returns (ok, what it said).
    The password is used for this one request and never printed or kept."""
    if not re.fullmatch(r"[\w.:-]+", ip or ""):
        raise SystemExit("bad TV_IP")
    base = "http://%s" % ip + (":%d" % RokuTV.DEV_PORT if RokuTV.DEV_PORT != 80 else "")
    mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    mgr.add_password(None, base, "rokudev", password if password is not None else _password())
    opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(mgr))
    data = open(zip_path, "rb").read() if zip_path else b""
    body, ctype = _multipart({"mysubmit": submit}, os.path.basename(zip_path) if zip_path else "", data)
    req = urllib.request.Request(base + "/plugin_install", data=body, headers={"Content-Type": ctype}, method="POST")
    try:
        with opener.open(req, timeout=60) as r:
            page = r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "the Roku refused the developer password (user rokudev)"
        return False, "the Roku answered %s" % e.code
    except (urllib.error.URLError, OSError) as e:
        return False, "could not reach the Roku's developer installer (%s). Is Developer Mode on?" % type(e).__name__
    m = re.search(r'<font color="red">(.*?)</font>', page, re.S)
    said = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip() if m else ""
    if submit == "Delete":   # Roku's page words for this are not documented: a 200 without "fail" counts
        return not re.search(r"fail|error", said, re.I), said or "removed"
    if re.search(r"Install Success|Application Received|Identical to previous", page, re.I):
        return True, said or "installed"
    return False, said or "the Roku did not say it installed (open http://<tv address> in a browser to see why)"


def install(ip, url, home_id, password=None):
    """Build the channel and sideload it. Replaces any sideloaded channel already there."""
    path = build(url, home_id)
    print("Installing guest-tv's channel on the Roku. This replaces any other sideloaded channel.", flush=True)
    ok, said = _installer(ip, "Replace", path, password)
    print(("Installed: " if ok else "Not installed: ") + said)
    if not ok:
        raise SystemExit(1)
    return ok


def uninstall(ip, password=None):
    """Remove the sideloaded channel (whatever "dev" is, which is guest-tv's after install)."""
    ok, said = _installer(ip, "Delete", None, password)
    print(("Removed: " if ok else "Not removed: ") + said)
    return ok


if __name__ == "__main__":
    print(SETUP)
