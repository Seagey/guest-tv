"""Put guest-tv on the TV with the couch-tv TV app, and take it off again.

The couch-tv TV app (couch-tv-home.apk, from github.com/Seagey/couch-tv/releases) shows a web page
full screen and opens the TV's real apps from it. Here it shows guest-tv instead of couch-tv.

    TV_IP=<tv address> .venv/bin/python tools/tv_app.py status            # what is on the TV now
    TV_IP=<tv address> .venv/bin/python tools/tv_app.py install couch-tv-home.apk
    TV_IP=<tv address> .venv/bin/python tools/tv_app.py open [--home guest]  # show guest-tv now
    TV_IP=<tv address> .venv/bin/python tools/tv_app.py home [--home guest]  # and make it the TV's home
    TV_IP=<tv address> .venv/bin/python tools/tv_app.py undo [--remove]      # put the old home back

`home` writes down the TV's old home first (tvs/<tv address>.home, never in git), and `undo` puts
that one back. `--url http://<this computer's address>:5410` if the guess of this computer's
address is wrong. Nothing here switches off or deletes anything on the TV.
"""
import os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import server, tvctl
from server import lan_ip

APP = "app.couchtv.launcher"
ACT = APP + "/.MainActivity"
PIECE = 16 * 1024   # some TVs stall on one big push, so the app goes over in small pieces


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and sys.argv.index(name) + 1 < len(sys.argv) else default


def current_home(tv):
    out = tv.sh("cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME", 15)
    lines = [l.strip() for l in out.splitlines() if "/" in l]
    return lines[-1] if lines else None


def installed(tv):
    return ("package:" + APP) in tv.sh("pm list packages " + APP, 15)


def install(tv, apk):
    tv.sh("echo ok")   # connect first (press Allow on the TV if it asks)
    data = open(apk, "rb").read()
    tmp = os.path.join(ROOT, ".apk-piece")
    tv.sh("rm -rf /data/local/tmp/gtv; mkdir -p /data/local/tmp/gtv")
    try:
        for n, i in enumerate(range(0, len(data), PIECE)):
            with open(tmp, "wb") as f:
                f.write(data[i:i + PIECE])
            with tv.lock:
                tv.dev.push(tmp, "/data/local/tmp/gtv/%05d" % n, read_timeout_s=30)
            if n % 80 == 79:
                print("  sent %d of %d KB" % ((i + PIECE) // 1024, len(data) // 1024), flush=True)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    out = tv.sh("cat /data/local/tmp/gtv/* > /data/local/tmp/gtv.apk && pm install -r /data/local/tmp/gtv.apk; "
                "rm -rf /data/local/tmp/gtv /data/local/tmp/gtv.apk", 240)
    print(out.strip())


def open_page(tv, url, home_id):
    if not re.fullmatch(r"https?://[\w.:-]+", url) or not re.fullmatch(r"[a-z0-9-]+", home_id):
        raise SystemExit("bad --url or --home")
    tv.sh("am force-stop %s; am start -n %s --es bridge %s --es tv %s" % (APP, ACT, url, home_id), 20)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    ip = os.environ.get("TV_IP")
    if not ip:
        raise SystemExit("Set TV_IP to the TV's address, for example: TV_IP=<tv address> .venv/bin/python tools/tv_app.py status")
    tv = tvctl.TV(ip)
    url = arg("--url") or "http://%s:%d" % (lan_ip(), server.PORT)
    home_id = arg("--home") or server.settings().get("default_home") or "guest"
    saved = os.path.join(ROOT, "tvs", ip.replace(":", "_") + ".home")
    if cmd == "status":
        print("couch-tv TV app installed:", "yes" if installed(tv) else "no")
        print("TV home now:", current_home(tv))
        print("guest-tv address it would open:", url + "/tv/?tv=" + home_id)
    elif cmd == "install":
        if len(sys.argv) < 3 or not os.path.isfile(sys.argv[2]):
            raise SystemExit("Give the app file: tools/tv_app.py install couch-tv-home.apk "
                             "(download it from github.com/Seagey/couch-tv/releases)")
        install(tv, sys.argv[2])
    elif cmd in ("open", "home"):
        if not installed(tv):
            raise SystemExit("The couch-tv TV app is not on this TV yet. Run: tools/tv_app.py install couch-tv-home.apk")
        if cmd == "home":
            before = current_home(tv)
            if before and not before.startswith(APP) and not os.path.exists(saved):
                os.makedirs(os.path.dirname(saved), exist_ok=True)
                open(saved, "w").write(before + "\n")
                print("Old home written down:", before)
            tv.sh("cmd package set-home-activity " + ACT, 15)
        open_page(tv, url, home_id)
        time.sleep(3)
        print("Showing %s/tv/?tv=%s on the TV." % (url, home_id) + (" The Home button now comes back here." if cmd == "home" else ""))
    elif cmd == "undo":
        before = open(saved).read().strip() if os.path.exists(saved) else None
        if before:
            tv.sh("cmd package set-home-activity " + before, 15)
            os.remove(saved)
            print("Home put back:", before)
        else:
            print("No old home written down for this TV. Pick the home in the TV's Settings (Apps, Default apps, Home).")
        if "--remove" in sys.argv:
            print(tv.sh("pm uninstall " + APP, 30).strip())
        tv.sh("input keyevent KEYCODE_HOME", 8)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
