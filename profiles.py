"""Guest profile picker: when a streaming app on the guest TV opens on "Who's watching?", press the
guest profile, so guests never land in the host's profile.

Watches the TV over ADB (the same key couch-tv uses). Only acts in the first moments after an app
opens, and only on a profile screen it can read, or (for apps that hide their screen from ADB, like
Netflix) on a cold start with a profile position the host set. Never presses anything else.

settings.json:
  "profiles": {
    "tv": "<the TV's IP address>",   (a number, not a .local name: two Android devices can end up
                                      with the same .local name, and then it can move to the other one)
    "names": ["Guest", "Guests", "Visitor"],
    "blind": {"com.netflix.ninja": {"position": 3, "wait": 9}}
  }
"""
import json, os, re, socket, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STREAMING = {"com.netflix.ninja", "com.amazon.amazonvideo.livingroom", "com.disney.disneyplus", "au.com.stan.and",
             "com.google.android.youtube.tv", "au.com.ninenow.ctv", "au.com.streamotion.ares", "com.cbs.ca",
             "com.apple.atve.androidtv.appletv", "au.com.seven", "au.com.tenplay", "au.net.abc.iview",
             "com.sbs.ondemand.tv", "com.foxtel.kayo", "tv.wuaki.apptv", "com.binge.android"}
WHO = re.compile(r"who.?s watching|who is watching|choose (?:a |your )?profile|select (?:a )?profile|switch profile", re.I)
UI_DUMP = "uiautomator dump /sdcard/gtv-ui.xml >/dev/null 2>&1; cat /sdcard/gtv-ui.xml; rm /sdcard/gtv-ui.xml"
LOG = os.path.join(HERE, "logs", "profiles.log")
state = {"last": None, "picked": {}, "seen": []}   # shown at /api/profiles


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    state["seen"] = (state["seen"] + [line])[-30:]
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def parse_ui(xml, focused=False):
    items = []
    for node in re.findall(r"<node [^>]*>", xml or ""):
        get = lambda n: (re.search(rf' {n}="([^"]*)"', node) or [None, ""])[1]
        label = (get("text") or get("content-desc")).replace("&amp;", "&").replace("&#39;", "'").strip()
        m = re.match(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", get("bounds"))
        has_focus = get("focused") == "true"
        if not m or not (label or (focused and has_focus)):
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        if x2 > x1 and y2 > y1:
            items.append({"label": label[:80], "x": (x1 + x2) // 2, "y": (y1 + y2) // 2, "focused": has_focus,
                          "box": (x1, y1, x2, y2)})
    return items


class Watcher(threading.Thread):
    def __init__(self, cfg):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.dev = None

    def host(self):
        return self.cfg.get("tv")

    def connect(self):
        from adb_shell.adb_device import AdbDeviceTcp
        from adb_shell.auth.sign_pythonrsa import PythonRSASigner
        priv = open(os.path.expanduser("~/.android/adbkey")).read()
        pub = open(os.path.expanduser("~/.android/adbkey.pub")).read()
        d = AdbDeviceTcp(self.host(), 5555, default_transport_timeout_s=10)
        d.connect(rsa_keys=[PythonRSASigner(pub, priv)], auth_timeout_s=5)
        self.dev = d

    def sh(self, cmd, t=20):
        return self.dev.shell(cmd, timeout_s=t, read_timeout_s=t)

    def front(self):
        out = self.sh("dumpsys activity activities | grep -m1 -E 'ResumedActivity'", 8)   # topResumedActivity, mResumedActivity or plain ResumedActivity, by Android version
        m = re.search(r"u0 ([^/\s]+)/", out)
        return m.group(1) if m else None

    def age(self, pkg):
        """Seconds since the app's process started (a cold start is young)."""
        out = self.sh(f"pid=$(pidof {pkg}); [ -n \"$pid\" ] && ps -o ETIME= -p ${{pid%% *}}", 8).strip()
        parts = [int(x) for x in re.split(r"[:-]", out) if x.isdigit()] if out else []
        if not parts:
            return 9999
        secs = 0
        for p in parts:
            secs = secs * 60 + p
        return secs

    def playing(self, pkg):
        out = self.sh("dumpsys media_session | grep -A12 'package=" + pkg + "' | grep -m1 'state=PlaybackState'", 8)
        return "state=3" in out   # 3 = PLAYING

    def names(self):
        return [norm(n) for n in self.cfg.get("names") or ["Guest", "Guests"]]

    def try_pick(self, pkg, cold):
        """Up to ~30 s after the app comes up: read the screen, press the guest profile if offered."""
        blind = (self.cfg.get("blind") or {}).get(pkg)
        end = time.time() + 30
        blank = 0
        while time.time() < end:
            time.sleep(2)
            if self.front() != pkg:
                return
            items = parse_ui(self.sh(UI_DUMP, 25))
            if not items:
                blank += 1
                if blind and cold and blank >= 2 and time.time() > end - 30 + blind.get("wait", 9):
                    if self.playing(pkg):
                        return
                    keys = " ".join(["KEYCODE_DPAD_RIGHT"] * (int(blind.get("position", 1)) - 1) + ["KEYCODE_DPAD_CENTER"])
                    for k in keys.split():
                        self.sh("input keyevent " + k, 8)
                        time.sleep(0.35)
                    state["picked"][pkg] = time.time()
                    log(f"{pkg}: screen hidden, cold start, pressed profile {blind.get('position')} blind")
                    return
                continue
            if any(WHO.search(i["label"]) for i in items):
                hit = next((i for n in self.names() for i in items if norm(i["label"]) == n), None)
                if not hit:
                    log(f"{pkg}: profile screen, no guest profile ({', '.join(i['label'] for i in items[:8])})")
                    return
                self.sh(f"input tap {hit['x']} {hit['y']}", 8)
                time.sleep(1.5)
                # Some apps (Stan) only move the focus on a tap. If the profile screen is still up and
                # the guest profile now has the focus, OK presses it.
                again = parse_ui(self.sh(UI_DUMP, 25), focused=True)
                if any(WHO.search(i["label"]) for i in again):
                    f = next((i for i in again if i.get("focused")), None)
                    inside = f and f["box"][0] <= hit["x"] <= f["box"][2] and f["box"][1] <= hit["y"] <= f["box"][3]
                    if f and (norm(f["label"]) in self.names() or inside):
                        self.sh("input keyevent KEYCODE_DPAD_CENTER", 8)
                    else:
                        log(f"{pkg}: tapped {hit['label']} but the focus is on {f['label'] if f else 'nothing'}; left it")
                        return
                state["picked"][pkg] = time.time()
                log(f"{pkg}: picked {hit['label']}")
                return
        log(f"{pkg}: no profile screen")

    def run(self):
        log("watching " + str(self.cfg.get("tv")))
        while True:
            try:
                if self.dev is None:
                    self.connect()
                pkg = self.front()
                if pkg != state["last"]:
                    prev, state["last"] = state["last"], pkg
                    if pkg in STREAMING and prev != pkg:
                        cold = self.age(pkg) < 20
                        log(f"{pkg} opened ({'cold start' if cold else 'from the background'})")
                        self.try_pick(pkg, cold)
                time.sleep(2.5)
            except Exception as e:
                # TV off or asleep: try again in a while, quietly
                if self.dev is not None:
                    try:
                        self.dev.close()
                    except Exception:
                        pass
                self.dev = None
                state["last"] = None
                time.sleep(30)


def start(settings):
    cfg = settings.get("profiles")
    if cfg and cfg.get("on", True):
        Watcher(cfg).start()
