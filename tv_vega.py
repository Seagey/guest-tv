"""guest-tv on a Fire TV running Vega OS (Fire TV Stick 4K Select and newer), for "tv_kind": "vega".

Cut down from couch-tv's bridge/vega.py (github.com/Seagey/couch-tv). Written from Amazon's Vega
documentation and checked against a stand-in on the computer (tools/vega_test.py), NOT yet on a real
Vega stick: first reports from real sticks wanted (docs/FIRE-VEGA.md).

Vega is not Android: no ADB, no APK, and no way to replace Amazon's home. What Amazon documents, and
what this driver uses:

- guest-tv is a small Vega app (tv-apps/vega/) that shows guest-tv's TV page in Amazon's WebView. The
  owner builds and installs it once with Amazon's own free tools (Developer Mode).
- Opening it from the computer: `vega device launch-app` (Amazon's CLI, over the network after
  `vega exec vda connect <ip>:5555`) when that is installed here, else DIAL. DIAL's Application-URL
  comes from the stick's own device description, read from an address the owner writes down once
  (data/vega-dial-<tv address>.key): this file never runs SSDP discovery. Whether DIAL launches a
  sideloaded app is not documented by Amazon, so the CLI goes first.
- Netflix and YouTube open through DIAL, as a phone's own Cast button does.
- Phone remote keys: Amazon documents no key injection on Vega. So the keys go to guest-tv's page
  itself: the page long polls the computer (page_keys) and presses them on itself. They work while
  guest-tv is in front. Volume, mute, power off and Home belong to the stick. Home on the phone opens
  guest-tv; Amazon's own Home button still opens Amazon's home.
- Which app is on screen is not readable. The one thing known: guest-tv's page is in front while it has
  recently polled for keys (couch-tv's page_seen idea).

Never reads or writes anything on the stick except through Amazon's own commands. Only fixed tables go
out: nothing a guest typed reaches the stick except a Netflix or YouTube id from tvbrands.
"""
import importlib.util, os, re, shutil, socket, subprocess, threading, time, urllib.error, urllib.parse, urllib.request

import tvbrands, tvctl
from tvbrands import TVUnavailable, _Base, _http, _read, _token_file, netflix_id, youtube_id

HERE = os.path.dirname(os.path.abspath(__file__))
VEGA_APP_DIR = os.path.join(HERE, "tv-apps", "vega")

# Amazon's Vega app ids look like "<package>.main": an inference from Amazon's templates, not a
# documented rule. tv-apps/vega/README.md says how to read the real one (`vega device installed-apps`).
APP_ID = "app.guesttv.home.main"
DIAL_NAME = "GuestTV"
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}")
DIAL_RE = re.compile(r"[A-Za-z0-9_.-]{1,40}")
HOST_RE = re.compile(r"[A-Za-z0-9.:-]{1,80}")
GUEST_ID = "guest-tv"   # what front() says while guest-tv's page is in front

# guest key name -> the key the page presses on itself (KeyboardEvent.key). Only these six: Amazon
# documents the arrow keys and Enter reaching a WebView page, and Escape for Back is couch-tv's choice.
KEYS = {"up": "ArrowUp", "down": "ArrowDown", "left": "ArrowLeft", "right": "ArrowRight",
        "ok": "Enter", "back": "Escape"}
# What the stick keeps for itself: nothing on Vega lets the network press these (couch-tv's NOT_POSSIBLE).
NOT_POSSIBLE = {"volume_up": "volume", "volume_down": "volume", "mute": "mute", "power": "power"}
# tvctl.APPS ids that open through DIAL, and DIAL's names for them.
DIAL_APPS = {"netflix": "Netflix", "youtube": "YouTube"}

SETUP = """\
Fire TV on Vega OS: guest-tv is an app you build once with Amazon's free tools.
1. Developer Mode on the stick (Settings, My Fire TV, About, press OK on the name seven times, then
   Developer options, Developer Mode) and `vega devmode login` on a Mac or Linux computer. Amazon's
   Vega tools and a free Amazon Developer account are needed. One USB cable step switches on network
   access: `vega exec vda tcpip 5555`.
2. `tools/tv_app.py install` writes the app's address file and prints the build and install steps
   (tv-apps/vega/README.md). Amazon's Home button still opens Amazon's home: Home on the phone remote
   brings guest-tv back.
3. Optional, for Netflix and YouTube titles: write the stick's DIAL device description address into
   data/vega-dial-<tv address>.key (one line, http://<tv address>:<port>/<path>).
Details: docs/FIRE-VEGA.md."""


def _config_module():
    spec = importlib.util.spec_from_file_location("vega_make_config", os.path.join(VEGA_APP_DIR, "make-config.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build(url, home_id):
    """There is nothing to pack here: Amazon's own `vega build` makes the app. This writes the one file
    the app imports (tv-apps/vega/src/guest.json, git ignored) and returns the folder to copy from."""
    mod = _config_module()
    mod.write(mod.build(url, home_id))
    return VEGA_APP_DIR


def install(ip, url, home_id):
    """Only prints Amazon's steps: couch-tv has no automated install for Vega either."""
    path = build(url, home_id)
    print("Wrote the app's address file in %s (src/guest.json, never in git)." % path)
    print("Now, once, with Amazon's tools (more in tv-apps/vega/README.md):")
    print("  vega project generate            (a blank project, name it guesttv)")
    print("  copy tv-apps/vega/src/App.tsx and src/guest.json over the project's src/")
    print("  add tv-apps/vega/manifest-additions.toml to the project's manifest.toml")
    print("  vega build")
    print("  vega device install-app --packagePath <the .vpkg> -d %s:%d" % (ip, VegaTV.PORT))
    print("  vega device launch-app --appName %s -d %s:%d" % (APP_ID, ip, VegaTV.PORT))
    print("Then: TV_KIND=vega TV_IP=%s .venv/bin/python tools/tv_app.py open" % ip)


def uninstall(ip):
    print("Remove guest-tv from the stick with Amazon's tool:")
    print("  vega device uninstall-app --appName %s -d %s:%d" % (APP_ID, ip, VegaTV.PORT))
    print("Developer Mode stays on until you switch it off (Settings, My Fire TV, About, Developer options).")


class VegaTV(_Base):
    kind = "vega"
    KEYS = KEYS
    can_open = True
    sees_front = True    # only "guest-tv or unknown": see front()
    pairing = None       # nothing to allow: Developer Mode was the one grant, made on the stick itself
    GONE_IS_OFF = 10     # a stick that left the Wi-Fi for a moment is not a switch off
    SETTLE = 8.0         # couch-tv: let Amazon's home finish drawing before ours goes in front
    PORT = 5555          # Vega's network developer port: open while the stick is awake (tests move it)
    PAGE_SEEN_FOR = 30.0 # the page polls about every 20 s, so it counts as in front a little longer
    KEY_FRESH = 10.0     # a key nobody collected within this long is dropped, never replayed later
    CLI = "vega"         # Amazon's Vega CLI, looked up on the PATH each time

    def __init__(self, ip):
        super().__init__(ip)
        self.cli_last = None        # what the last Amazon command said, for the status command
        self.desc_url = None        # DIAL device description address (the owner's file, or set by a test)
        self.dial_base = None       # DIAL's Application-URL, read from that description
        self.page_seen = 0.0        # when guest-tv's page last asked for keys
        self._cv = threading.Condition()
        self._keys = []             # [(n, name, when)] waiting for the page
        self._n = 0

    def guest_id(self):
        return GUEST_ID

    # ---------- what the stick answers ----------
    def is_on(self):
        """True when the developer port answers (awake), False when the stick is there but the port is
        closed (standby, or network access not switched on), None when nothing answers at all."""
        try:
            socket.create_connection((self.ip, self.PORT), 1.5).close()
            return True
        except ConnectionRefusedError:
            return False
        except OSError:
            return None

    def page_in_front(self):
        return bool(self.page_seen) and time.monotonic() - self.page_seen < self.PAGE_SEEN_FOR

    def front(self):
        """guest-tv while its page is polling for keys, else None: Vega cannot say what else is on screen."""
        return GUEST_ID if self.page_in_front() else None

    # ---------- Amazon's CLI ----------
    def _cli(self, *args, timeout=25):
        """One `vega ...` command. A list of arguments, never a shell string."""
        exe = shutil.which(self.CLI)
        if not exe:
            raise TVUnavailable("Amazon's Vega CLI is not installed on this computer")
        try:
            p = subprocess.run([exe] + list(args), capture_output=True, text=True, timeout=timeout,
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise TVUnavailable("Amazon's Vega CLI did not answer in time") from None
        except OSError as e:
            raise TVUnavailable("could not run the Vega CLI (%s)" % type(e).__name__) from None
        self.cli_last = "%s: %s" % (" ".join(args[:3]), "ok" if p.returncode == 0 else "failed")
        if p.returncode != 0:
            raise TVUnavailable("the Vega CLI said no: %s" % ((p.stdout + p.stderr).strip()[-160:] or "no reason given"))
        return p.stdout.strip()

    def _target(self):
        if not HOST_RE.fullmatch(str(self.ip)):
            raise TVUnavailable("the TV address does not look like an address")
        return "%s:%d" % (self.ip, self.PORT)

    def _cli_launch(self, app_id):
        if not ID_RE.fullmatch(str(app_id)):
            raise ValueError("not a Vega app id: %s" % app_id)
        target = self._target()
        self._cli("exec", "vda", "connect", target)   # Amazon's step, harmless to repeat
        self._cli("device", "launch-app", "--appName", str(app_id), "-d", target, timeout=35)

    # ---------- DIAL ----------
    def _dial_url(self):
        """DIAL's Application-URL, from the stick's own device description. No SSDP here: the
        description's address is the owner's one line in data/vega-dial-<ip>.key (or self.desc_url)."""
        if self.dial_base:
            return self.dial_base
        desc = self.desc_url or _read(_token_file("vega-dial", self.ip))
        if not desc:
            raise TVUnavailable("Netflix and YouTube titles are not set up for this stick (docs/FIRE-VEGA.md, DIAL)")
        u = urllib.parse.urlparse(desc)
        if u.scheme != "http" or u.hostname != self.ip:
            raise TVUnavailable("the DIAL address must be an http address on the stick itself")
        try:
            with urllib.request.urlopen(urllib.request.Request(desc), timeout=4) as r:
                base = r.headers.get("Application-URL")
        except (urllib.error.URLError, OSError) as e:
            raise TVUnavailable("could not read the stick's DIAL description (%s)" % type(e).__name__) from None
        if not base:
            raise TVUnavailable("the stick's DIAL description had no Application-URL")
        if urllib.parse.urlparse(base).hostname != self.ip:   # only ever talk to the stick itself
            raise TVUnavailable("the DIAL address did not match the stick, left alone")
        self.dial_base = base.rstrip("/")
        return self.dial_base

    def _dial(self, name, method="POST", body=""):
        if not DIAL_RE.fullmatch(name):
            raise ValueError("not a DIAL app name: %s" % name)
        try:
            code, _ = _http(method, "%s/%s" % (self._dial_url(), name), body if method == "POST" else None,
                            {"Content-Type": "text/plain; charset=utf-8"}, timeout=6)
        except (urllib.error.URLError, OSError) as e:
            self.dial_base = None
            raise TVUnavailable("DIAL did not answer (%s)" % type(e).__name__) from None
        return code

    def _dial_launch(self, name, body=""):
        code = self._dial(name, "POST", body)
        if code == 404:
            raise TVUnavailable("the stick does not know %s over DIAL" % name)
        if code >= 400:
            raise TVUnavailable("DIAL said %s for %s" % (code, name))

    # ---------- apps ----------
    def app_ids(self):
        """Vega lists no apps to the network. Netflix and YouTube are here when the stick's DIAL says it
        knows them; with no DIAL address written down there are none to offer. Every 30 min."""
        at, found = self.found
        if found and time.time() - at < 1800:
            return found
        if not self.is_on():
            raise TVUnavailable("the TV is not answering")
        try:
            self._dial_url()
        except TVUnavailable as e:
            if "not set up" in str(e):
                return {}
            raise
        found = {}
        for app_id, name in DIAL_APPS.items():
            if self._dial(name, "GET") == 200:
                found[app_id] = name
        if found:
            self.found = (time.time(), found)
        return found

    def launch(self, tid):
        if tid not in DIAL_APPS.values() and tid != DIAL_NAME:
            raise TVUnavailable("on a Vega stick only guest-tv, Netflix and YouTube open from the computer")
        self._dial_launch(tid)

    def open_guest_app(self):
        """Open guest-tv's app: Amazon's CLI when it is here, else DIAL."""
        self.quiet()
        errs = []
        if shutil.which(self.CLI):
            try:
                return self._cli_launch(APP_ID)
            except (TVUnavailable, ValueError) as e:
                errs.append(str(e))
        try:
            return self._dial_launch(DIAL_NAME)
        except TVUnavailable as e:
            errs.append(str(e))
        raise TVUnavailable("could not open guest-tv on the stick: " + "; ".join(errs))

    def open_link(self, uri, app_id):
        """Netflix and YouTube open the title (DIAL, couch-tv's payloads, never checked on a real stick);
        every other app is not reachable from the computer."""
        self.quiet(40)
        nid, yid = netflix_id(uri), youtube_id(uri)
        try:
            if app_id == "netflix" and nid:
                self._dial_launch("Netflix", "m=" + urllib.parse.quote("https://www.netflix.com/watch/%s" % nid, safe=""))
                return "show"
            if app_id == "youtube" and yid:
                self._dial_launch("YouTube", "v=" + urllib.parse.quote(yid, safe=""))
                return "show"
        except TVUnavailable:
            pass
        self.open_app(app_id)
        return "app"

    # ---------- keys, through the page ----------
    def push_key(self, name):
        """Queue one guest key for the page. Only the names in KEYS."""
        if name not in KEYS:
            raise KeyError(name)
        with self._cv:
            self._n += 1
            self._keys = (self._keys + [(self._n, name, time.monotonic())])[-50:]
            self._cv.notify_all()
        return self._n

    def page_keys(self, after, timeout=20.0):
        """The page's long poll (the lead's GET /api/tv/keys): blocks until a key newer than `after`
        arrives or `timeout` runs out, and marks the page as seen. Returns
        {"n": <number of the last key issued>, "keys": [<names newer than after>]}. A page that
        remembers a number from before the computer restarted (after bigger than n) starts again from
        the beginning; keys nobody collected within KEY_FRESH seconds are not replayed."""
        try:
            after = int(after)
        except (TypeError, ValueError):
            after = 0
        timeout = max(0.0, min(float(timeout), 30.0))
        end = time.monotonic() + timeout
        self.page_seen = time.monotonic()
        with self._cv:
            while True:
                now = time.monotonic()
                if after > self._n:
                    after = 0
                new = [name for n, name, when in self._keys if n > after and now - when <= self.KEY_FRESH]
                if new or now >= end:
                    self.page_seen = time.monotonic()
                    return {"n": self._n, "keys": new}
                self._cv.wait(min(0.25, max(0.01, end - now)))

    def button(self, code):
        """A key for the page. It only means something while guest-tv is in front."""
        if not self.page_in_front():
            raise TVUnavailable("guest-tv is not on the TV's screen, so there is nothing to press the key on: "
                                "press Home on the phone remote to open it first")
        self.push_key(code)

    def key(self, name, times=1):
        self.quiet()
        if name == "home":
            return self.open_guest_app()
        if name in NOT_POSSIBLE:
            raise TVUnavailable("%s belongs to the Fire TV stick: nothing on a Vega stick lets the phone "
                                "press it, so use the stick's own remote" % NOT_POSSIBLE[name])
        if name not in tvctl.KEYS:
            raise KeyError(name)
        if name not in KEYS:
            raise TVUnavailable("the phone remote presses the arrows, OK and Back on a Vega stick, not %s"
                                % name.replace("_", " "))
        for _ in range(max(1, min(int(times), 10))):
            self.button(name)

    def volume(self, up):
        raise TVUnavailable("volume belongs to the Fire TV stick: use the stick's own remote")

    def mute(self, on=None):
        raise TVUnavailable("mute belongs to the Fire TV stick: use the stick's own remote")
