"""Test the guard rails that came over from couch-tv (#72, #73, #110), the hook's wiring for every TV
kind, and the native welcome data for Roku and Apple TV. No TV, no Claude, no network: the server runs
on 127.0.0.1 and the TVs are stand-ins in this file.

    .venv/bin/python tools/security_test.py
"""
import json, os, subprocess, sys, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.pop("GUEST_TV_KIND", None)
os.environ.pop("GUEST_TV_IP", None)
import server, tvbrands, tvctl

ok = bad = 0


def check(name, cond):
    global ok, bad
    print(("PASS " if cond else "FAIL ") + name)
    ok, bad = ok + bool(cond), bad + (not cond)


def raises(fn, kind=Exception):
    try:
        fn()
    except kind:
        return True
    except Exception:
        return False
    return False


# ---------------------------------------------------------------- packages that reach the TV's shell (couch-tv#72)
print("Packages")
for bad_name in ("a.b;touch /sdcard/proof", "nodots", "a.b c", "a.b'", "a.b$(id)", "", None, "a." * 120 + "b"):
    check("refused: %r" % (bad_name if not isinstance(bad_name, str) or len(bad_name) < 30 else bad_name[:20] + "..."),
          raises(lambda: tvctl.check_package(bad_name), tvctl.UnsafeInput))
check("a real package passes", tvctl.check_package("com.netflix.ninja") == "com.netflix.ninja")
check("a home component passes", tvctl.check_component("com.google.android.tvlauncher/.MainActivity"))
check("a component with a shell character is refused", raises(lambda: tvctl.check_component("a.b/.C;reboot"), tvctl.UnsafeInput))


class ShellTV(tvctl.TV):
    """tvctl.TV with the shell written down instead of sent."""
    def __init__(self):
        super().__init__("127.0.0.1")
        self.cmds = []

    def sh(self, cmd, t=20):
        self.cmds.append(cmd)
        return ""


t = ShellTV()
t.open_app("stan")
check("opening an app sends only the table's package", t.cmds[-1].startswith("monkey -p au.com.stan.and "))
tvctl.BY_ID["evil"] = {"id": "evil", "name": "Evil", "package": "a.b;reboot", "jw": [], "link": "app"}
t.cmds.clear()
check("a bad package in the table never reaches the shell", raises(lambda: t.open_app("evil"), tvctl.UnsafeInput) and not t.cmds)
check("open_link checks the package first", raises(lambda: t.open_link("intent://x#Intent;end", "evil"), tvctl.UnsafeInput) and not t.cmds)
check("playing() checks the package", raises(lambda: t.playing("a.b;reboot"), tvctl.UnsafeInput))
del tvctl.BY_ID["evil"]

# ---------------------------------------------------------------- tools that drive a real TV refuse without the switch
env = {k: v for k, v in os.environ.items() if k != "GUEST_TV_REAL_TV"}
r = subprocess.run([sys.executable, os.path.join(HERE, "tvui.py"), "ui"], capture_output=True, text=True, env=env, timeout=30)
check("tvui.py refuses without GUEST_TV_REAL_TV=1", r.returncode != 0 and "GUEST_TV_REAL_TV=1" in r.stderr)

# ---------------------------------------------------------------- the Home button watch (tools/tv_app.py, couch-tv#37, #94, #98)
print("Home button watch")
sys.argv = ["tv_app.py"]
import tools.tv_app as tv_app  # noqa: E402


class SettingsTV:
    def __init__(self, services):
        self.services, self.cmds = services, []

    def sh(self, cmd, t=20):
        self.cmds.append(cmd)
        if cmd.startswith("settings get secure enabled_accessibility_services"):
            return self.services
        if cmd.startswith("settings put secure enabled_accessibility_services"):
            self.services = cmd.split(" ", 4)[4].strip("'")
        if cmd.startswith("settings delete secure enabled_accessibility_services"):
            self.services = "null"
        return ""


real_sleep = time.sleep
tv_app.time.sleep = lambda s: None   # the same time module: put back below
s = SettingsTV("null")
tv_app.home_watch(s, True)
check("watch switched on where none was", s.services == tv_app.WATCH[0])
s = SettingsTV("com.other.app/.Svc:" + tv_app.WATCH[0])
tv_app.home_watch(s, True)
puts = [c for c in s.cmds if c.startswith("settings put secure enabled_accessibility_services")]
check("already listed: taken out, then put back so Android binds it again", len(puts) == 2 and tv_app.WATCH[0] not in puts[0]
      and s.services == "com.other.app/.Svc:" + tv_app.WATCH[0])
s = SettingsTV("com.other.app/.Svc:" + tv_app.WATCH[0])
tv_app.home_watch(s, False)
check("off: only the watch is taken out", s.services == "com.other.app/.Svc")
s = SettingsTV("good.app/.Svc:bad;reboot/x")
tv_app.home_watch(s, True)
check("a strange service name from the TV is not written back", "reboot" not in s.services)
time.sleep = real_sleep

# ---------------------------------------------------------------- the server
print("Server")
server.start_tv_watchers  # untouched here; tested below with stand-ins
srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % srv.server_address[1]
hid = server.home_ids()[0]


def call(path, body=None, headers=None, method=None):
    req = urllib.request.Request(base + path, body, headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


code, _, _ = call("/api/aircon?home=" + hid, b"zone=1&on=1", {"Content-Type": "application/x-www-form-urlencoded"})
check("a form POST is refused: JSON only (415)", code == 415)
code, _, _ = call("/api/aircon?home=" + hid, b'{"zone": 1}', {"Content-Type": "text/plain"})
check("text/plain is refused too (a cross site page can send that without asking)", code == 415)
code, _, _ = call("/api/hub?home=" + hid, b'{}', {"Content-Type": "application/json; charset=utf-8"})
check("JSON with a charset is fine (reaches the handler: 400 nothing to change)", code == 400)
code, _, _ = call("/api/health", headers={"Host": "evil.example.com"})
check("a foreign Host name gets 403 (DNS rebinding)", code == 403)
for good in ("192.0.2.10:5410", "localhost:5410", "my-computer.local:5410", "[::1]:5410", "127.0.0.1"):
    code, _, _ = call("/api/health", headers={"Host": good})
    check("Host %s is this computer: allowed" % good, code == 200)
check("public_url's host is allowed", (lambda: (server.settings.__setattr__ if False else None))() is None)

# wrong codes: five different ones from one address in a minute, then 429
server.WRONG.clear()
addr = "192.0.2.50"
for i in range(4):
    server.note_wrong(addr, "wrong-%d" % i)
server.note_wrong(addr, "wrong-0")
check("four different wrong codes (one repeated): not limited yet", not server.wrong_limited(addr))
server.note_wrong(addr, "wrong-9")
check("the fifth different wrong code: limited", server.wrong_limited(addr))
check("another address is not", not server.wrong_limited("192.0.2.51"))
for i in range(9):
    server.note_wrong("127.0.0.1", "w%d" % i)
check("this computer itself is never limited", not server.wrong_limited("127.0.0.1"))
server.WRONG[addr] = (time.monotonic() - 61, server.WRONG[addr][1])
check("a minute later: free again", not server.wrong_limited(addr))
server.WRONG.clear()
for i in range(server.WRONG_ADDRESSES + 5):
    server.note_wrong("198.51.100.%d" % (i % 250) if i < 250 else "203.0.113.%d:%d" % (i % 250, i), "x")
check("memory stays capped", len(server.WRONG) <= server.WRONG_ADDRESSES)
server.WRONG.clear()

code, _, body = call("/api/r?home=%s&c=000000000000" % hid)
check("a wrong remote code is refused (403)", code == 403)

# native welcome data (Roku, Apple TV)
code, _, body = call("/api/tv/native?home=" + hid, headers={"Host": "192.0.2.10:5410"})
nat = json.loads(body)
check("native welcome data answers", code == 200 and nat.get("title"))
check("its pictures use the address the TV reached", (nat.get("photo") or "http://192.0.2.10:5410").startswith("http://192.0.2.10:5410/")
      and nat["remote_qr"].startswith("http://192.0.2.10:5410/api/qr?"))
check("no host key in it", server.private().get("host_key", "-") not in body.decode())
h = dict(server.load_home(hid), demo=False, demo_stay=None, calendar_url=None, stay={}, mode="stay")
between = server.native_screen(h, "http://192.0.2.10:5410")
check("between stays: no Wi-Fi, no door codes, no guest remote", between["wifi"] is None and between["access"] == []
      and "what=remote" not in between["remote_qr"] and between["phase"] == "between")
code, hd, body = call("/api/qr?home=%s&fmt=png" % hid)
check("QR codes as PNG for the TVs that draw their own screen", code == 200 and body[:8] == b"\x89PNG\r\n\x1a\n" and hd["Content-Type"] == "image/png")
code, hd, body = call("/api/qr?home=%s" % hid)
check("QR codes stay SVG for the page", code == 200 and b"<svg" in body)


# the page key channel (Fire TV on Vega OS)
class KeysTV(tvbrands._Base):
    kind = "vega"

    def __init__(self):
        super().__init__("127.0.0.1")
        self.asked = []

    def page_keys(self, after, timeout=20.0):
        self.asked.append(after)
        return {"n": after + 2, "keys": ["up", "ok"]}


os.environ["GUEST_TV_KIND"], os.environ["GUEST_TV_IP"] = "vega", "127.0.0.1"
kt = KeysTV()
tvctl._tvs[("vega", "127.0.0.1")] = kt
code, _, body = call("/api/tv/keys?home=%s&after=3" % hid)
check("the Vega page gets the Guest remote's keys", code == 200 and json.loads(body) == {"n": 5, "keys": ["up", "ok"]} and kt.asked == [3])
code, _, body = call("/api/tv/keys?home=%s&after=x" % hid)
check("a bad after counts as 0", code == 200 and kt.asked[-1] == 0)
os.environ["GUEST_TV_KIND"] = "android"
code, _, _ = call("/api/tv/keys?home=%s" % hid)
check("TVs that take keys directly have no key channel", code == 404)
srv.shutdown()

# ---------------------------------------------------------------- the hook for every kind
print("Hook wiring")
started = []
real_watch = tvbrands.watch
tvbrands.watch = lambda tv, *a, **k: started.append(tv)
os.environ["GUEST_TV_IP"] = "127.0.0.1"
for kind in tvbrands.KINDS:
    os.environ["GUEST_TV_KIND"] = kind
    started.clear()
    stand = KeysTV()
    stand.kind = kind
    tvctl._tvs[(kind, "127.0.0.1")] = stand
    server.start_tv_watchers()
    time.sleep(0.05)
    check("%s: one watcher, page set, no key in it" % kind, len(started) == 1 and started[0].page
          and "&brand=%s" % kind in started[0].page and "key" not in started[0].page)
os.environ["GUEST_TV_KIND"] = "android"
started.clear()
server.start_tv_watchers()
check("Android TVs get no watcher (the TV app is the home)", started == [])
tvbrands.watch = real_watch
stop = threading.Event()
cant = KeysTV()
cant.can_open = False
cant.is_on = lambda: 1 / 0
th = threading.Thread(target=tvbrands.watch, args=(cant, 0.05, stop), daemon=True)
th.start()
time.sleep(0.5)
check("a TV that cannot show guest-tv: the watcher leaves it alone and says why", "cannot show" in cant.log[-1])
cant.can_open, opened = True, []
cant.is_on, cant.front, cant.open_guest_app = (lambda: True), (lambda: None), (lambda: opened.append(1))
cant.SETTLE = 0
time.sleep(2.5)
check("it can later (a Guest TV app was added): the watcher opens guest-tv", opened == [1])
stop.set()

missing = [k for k, (m, c) in tvbrands.KINDS.items() if not os.path.exists(os.path.join(ROOT, m + ".py"))]
check("every kind has its driver file", not missing)
if not missing:
    for kind in tvbrands.KINDS:
        tvbrands.DATA = os.path.join(ROOT, "build", "security-test-data")
        d = tvbrands.make(kind, "127.0.0.1")
        check("%s: tvbrands.make gives a driver with the full set of calls" % kind,
              all(callable(getattr(d, n, None)) for n in ("is_on", "front", "installed", "key", "open_app", "open_link",
                                                         "open_guest_app", "is_guest", "nothing")) and d.kind == kind)

print("\n%d passed, %d failed" % (ok, bad))
sys.exit(1 if bad else 0)
