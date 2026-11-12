"""Step through the guest TCL by hand (for setting up app profiles). One command per run:

  tvui.py open <pkg>            open an app (launcher entry)
  tvui.py ui                    list what is on screen: * focused, label @x,y
  tvui.py shot <out.png>        screenshot
  tvui.py key KEY [KEY ...]     press keys, e.g. DPAD_RIGHT DPAD_CENTER BACK
  tvui.py tap X Y               tap a point
  tvui.py text WORD             type text into the focused box
  tvui.py stop <pkg>            close an app

It drives a real TV, so it refuses to run unless GUEST_TV_REAL_TV=1 is set (as couch-tv's real TV
scripts do): an agent running the tests can never press anything on a TV by accident.

    GUEST_TV_REAL_TV=1 TV_IP=<tv address> .venv/bin/python tools/tvui.py ui
"""
import os, re, sys, time

if os.environ.get("GUEST_TV_REAL_TV") != "1":
    sys.exit("tvui.py talks to a real TV. Mute the TV, make sure the owner knows, then run it with GUEST_TV_REAL_TV=1.")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tvctl import check_package
from adb_shell.adb_device import AdbDeviceTcp
from adb_shell.auth.sign_pythonrsa import PythonRSASigner

priv = open(os.path.expanduser("~/.android/adbkey")).read()
pub = open(os.path.expanduser("~/.android/adbkey.pub")).read()
d = AdbDeviceTcp(os.environ["TV_IP"], 5555, default_transport_timeout_s=60)
d.connect(rsa_keys=[PythonRSASigner(pub, priv)], auth_timeout_s=60)
sh = lambda c, t=60: d.shell(c, timeout_s=t, read_timeout_s=t)
cmd, a = sys.argv[1], sys.argv[2:]
if cmd == "open":
    sh(f"monkey -p {check_package(a[0])} -c android.intent.category.LEANBACK_LAUNCHER 1 >/dev/null 2>&1")
elif cmd == "stop":
    sh(f"am force-stop {check_package(a[0])}")
elif cmd == "ui":
    xml = sh("uiautomator dump /sdcard/u.xml >/dev/null 2>&1; cat /sdcard/u.xml; rm /sdcard/u.xml", 90)
    for node in re.findall(r"<node [^>]*>", xml):
        g = lambda n: (re.search(rf' {n}="([^"]*)"', node) or [None, ""])[1]
        lab = (g("text") or g("content-desc")).strip()
        foc = g("focused") == "true"
        m = re.match(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", g("bounds"))
        if (lab or foc) and m:
            x1, y1, x2, y2 = map(int, m.groups())
            print(("* " if foc else "  ") + lab[:70] + f" @{(x1 + x2) // 2},{(y1 + y2) // 2}")
    if "<node" not in xml:
        print("(screen hidden from ADB)")
elif cmd == "shot":
    sh("screencap -p /sdcard/s.png")
    d.pull("/sdcard/s.png", a[0])
    print(a[0])
elif cmd == "key":
    for k in a:
        if not re.fullmatch(r"[A-Z0-9_]{1,32}", k):
            sys.exit("not a key name: " + k[:40])
        sh("input keyevent KEYCODE_" + k)
        time.sleep(0.5)
elif cmd == "tap":
    sh(f"input tap {int(a[0])} {int(a[1])}")
elif cmd == "text":
    sh("input text '%s'" % re.sub(r"[^\w@.-]", "", a[0])[:60])
d.close()
