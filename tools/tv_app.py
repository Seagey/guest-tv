"""Put guest-tv on the TV, and take it off again.

Google TV and Android TV: the couch-tv TV app (couch-tv-home.apk, from
github.com/Seagey/couch-tv/releases) shows a web page full screen and opens the TV's real apps from
it. Here it shows guest-tv instead of couch-tv, and can become the TV's home screen.

    TV_IP=<tv address> .venv/bin/python tools/tv_app.py status            # what is on the TV now
    TV_IP=<tv address> .venv/bin/python tools/tv_app.py install couch-tv-home.apk
    TV_IP=<tv address> .venv/bin/python tools/tv_app.py open [--home guest]  # show guest-tv now
    TV_IP=<tv address> .venv/bin/python tools/tv_app.py home [--home guest]  # and make it the TV's home
    TV_IP=<tv address> .venv/bin/python tools/tv_app.py undo [--remove]      # put the old home back

Fire TV (Fire OS 6 and newer, a couch-tv release newer than 0.3): the same commands. Amazon's Home key ignores
the default home, so `home` also switches on the couch-tv app's Home button watch, and `undo`
switches it off. Amazon's home still flashes up for a moment before guest-tv comes back.

Samsung and LG (TV_KIND=samsung or lg, or "tv_kind" in data/settings.json): these TVs let no app
replace their home screen, so guest-tv is an app the computer opens each time the TV comes on.

    .venv/bin/python tools/tv_app.py build samsung|lg [--home guest]       # pack the app (build/)
    TV_KIND=samsung TV_IP=<tv address> .venv/bin/python tools/tv_app.py install
    TV_KIND=samsung TV_IP=<tv address> .venv/bin/python tools/tv_app.py pair   # press Allow on the TV
    TV_KIND=samsung TV_IP=<tv address> .venv/bin/python tools/tv_app.py open
    TV_KIND=samsung TV_IP=<tv address> .venv/bin/python tools/tv_app.py undo --remove

`home` writes down the TV's old home first (tvs/<tv address>.home, never in git), and `undo` puts
that one back. `--url http://<this computer's address>:5410` if the guess of this computer's
address is wrong. Nothing here switches off or deletes anything on the TV, except `undo --remove`,
which removes guest-tv's own app.
"""
import io, json, os, re, shutil, subprocess, sys, tarfile, time, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import server, tvctl
from server import lan_ip

APP = "app.couchtv.launcher"
ACT = APP + "/.MainActivity"
PIECE = 16 * 1024   # some TVs stall on one big push, so the app goes over in small pieces
APPS_DIR = os.path.join(ROOT, "tv-apps")
BUILD = os.path.join(ROOT, "build")
WGT = os.path.join(BUILD, "GuestTV.wgt")
IPK = os.path.join(BUILD, "app.guesttv.home_1.0.0_all.ipk")


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and sys.argv.index(name) + 1 < len(sys.argv) else default


def current_home(tv):
    out = tv.sh("cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME", 15)
    lines = [l.strip() for l in out.splitlines() if "/" in l]
    return lines[-1] if lines else None


def installed(tv):
    return ("package:" + APP) in tv.sh("pm list packages " + APP, 15)


FIRE_HOME = "com.amazon.tv.launcher"
WATCH = (APP + "/.FireWatch", APP + "/" + APP + ".FireWatch")   # how Android may write it down


def is_fire(tv):
    return ("package:" + FIRE_HOME) in tv.sh("pm list packages " + FIRE_HOME, 15)


def fire_watch(tv, on):
    """Fire TV starts Amazon's home from the Home key and ignores the default home, so the couch-tv
    app's own watcher (an accessibility service that only sees which window came forward) puts
    guest-tv back on top. Switched on and off here over ADB. Android drops the watcher whenever the
    app is stopped or updated, so this runs after the app is opened, and the secure-settings grant
    lets the app put it back by itself after updates and reboots. Off takes the grant away first."""
    tv.sh("pm %s %s android.permission.WRITE_SECURE_SETTINGS" % ("grant" if on else "revoke", APP), 10)
    cur = tv.sh("settings get secure enabled_accessibility_services", 10).strip()
    keep = [s for s in cur.split(":") if s and s != "null" and s not in WATCH]
    if on:
        keep.append(WATCH[0])
    if keep:
        tv.sh("settings put secure enabled_accessibility_services '%s'" % ":".join(keep), 10)
    else:
        tv.sh("settings delete secure enabled_accessibility_services", 10)
    if on:
        tv.sh("settings put secure accessibility_enabled 1", 10)


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


# ---------------------------------------------------------------- Samsung and LG apps

def stage(brand, url, home_id):
    """The app's files: tv-apps/<brand>/, boot.html, and settings.js saying where the computer is."""
    files = {}
    for name in os.listdir(os.path.join(APPS_DIR, brand)):
        files[name] = open(os.path.join(APPS_DIR, brand, name), "rb").read()
    files["boot.html"] = open(os.path.join(APPS_DIR, "boot.html"), "rb").read()
    files["settings.js"] = ("window.GUEST_TV = %s;\n" % json.dumps({"url": url, "home": home_id, "brand": brand})).encode()
    return files


def _tar_gz(entries):
    buf = io.BytesIO()
    now = int(time.time())
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as t:
        for name, data in entries:
            info = tarfile.TarInfo(name)
            info.mtime, info.uid, info.gid, info.uname, info.gname = now, 0, 0, "root", "root"
            if data is None:
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                t.addfile(info)
            else:
                info.size, info.mode = len(data), 0o644
                t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _ar(members):
    """A System V "ar" archive, as LG's ares-package writes it."""
    out = [b"!<arch>\n"]
    now = str(int(time.time())).encode()
    for name, data in members:
        out.append(name.encode().ljust(16) + now.ljust(12) + b"0".ljust(6) + b"0".ljust(6)
                   + b"100644".ljust(8) + str(len(data)).encode().ljust(10) + b"\x60\n")
        out.append(data)
        if len(data) % 2:
            out.append(b"\n")
    return b"".join(out)


def build(brand, url, home_id):
    """Samsung: an unsigned .wgt (Apps2Samsung signs it with your own certificate as it installs).
    LG: an .ipk laid out as LG's ares-package lays it out (from couch-tv's lg/build.py)."""
    if brand not in ("samsung", "lg"):
        raise SystemExit("build samsung or build lg")
    if not re.fullmatch(r"https?://[\w.:-]+", url) or not re.fullmatch(r"[a-z0-9-]+", home_id):
        raise SystemExit("bad --url or --home")
    os.makedirs(BUILD, exist_ok=True)
    files = stage(brand, url, home_id)
    if brand == "samsung":
        with zipfile.ZipFile(WGT, "w", zipfile.ZIP_DEFLATED) as z:
            for name in sorted(files):
                z.writestr(name, files[name])
        return WGT
    info = json.loads(files["appinfo.json"])
    app_id, version = info["id"], info["version"]
    entries = [(d + "/", None) for d in ("usr", "usr/palm", "usr/palm/applications", "usr/palm/packages",
                                         "usr/palm/applications/" + app_id, "usr/palm/packages/" + app_id)]
    entries += [("usr/palm/applications/%s/%s" % (app_id, n), files[n]) for n in sorted(files)]
    entries.append(("usr/palm/packages/%s/packageinfo.json" % app_id,
                    json.dumps({"id": app_id, "version": version, "app": app_id}, indent=2).encode() + b"\n"))
    control = "\n".join([
        "Package: " + app_id, "Version: " + version, "Section: misc", "Priority: optional", "Architecture: all",
        "Installed-Size: %d" % sum(len(v) for v in files.values()), "Maintainer: N/A <nobody@example.com>",
        "Description: This is a webOS application.", "webOS-Package-Format-Version: 2",
        "webOS-Packager-Version: x.y.x"]) + "\n"
    with open(IPK, "wb") as f:
        f.write(_ar([("debian-binary", b"2.0\n"), ("control.tar.gz", _tar_gz([("control", control.encode())])),
                     ("data.tar.gz", _tar_gz(entries))]))
    return IPK


def tool(name, *extra):
    """A TV maker's install tool: on the PATH, or Apps2Samsung where its desktop app puts it."""
    for p in [shutil.which(name)] + [os.path.expanduser(x) for x in extra]:
        if p and os.path.exists(p):
            return p
    return None


def brand_main(cmd, kind, ip, url, home_id):
    import tvbrands
    tv = tvctl.tv_for(ip, kind)
    guest = tvbrands.GUEST_APP[kind]
    if cmd == "status":
        on = tv.is_on()
        print("TV answers:", {True: "yes, on", False: "yes, in standby", None: "no"}[on])
        if on:
            front = tv.front()
            print("On screen:", front or "nothing (live TV, an input or the TV's menu)")
            print("guest-tv app on screen:", "yes" if front == guest else "no")
            print("Guest apps found:", ", ".join(a["name"] for a in tv.installed()) or "none")
        print("guest-tv address the app opens:", url + "/tv/?tv=" + home_id)
    elif cmd == "pair":
        print("Look at the TV: press Allow (Samsung) or Accept (LG). Waiting up to 60 seconds...", flush=True)
        tv.pair(60)
        print("Paired. The key is kept in data/ (never in git).")
    elif cmd == "install":
        path = build(kind, url, home_id)
        if kind == "samsung":
            cli = tool("apps2samsung-cli", "~/Applications/apps2samsung/cli/apps2samsung-cli")
            if not cli:
                raise SystemExit("Install Apps2Samsung first (README, Samsung). Then run this again.")
            print("Installing with Apps2Samsung. The first time, a browser opens for your Samsung account sign-in.", flush=True)
            subprocess.run([cli, "install", path, "--tv", ip, "--yes"], check=True)
        else:
            ares = tool("ares-install")
            if not ares:
                raise SystemExit("Install LG's tools first: npm install -g @webos-tools/cli (README, LG). Then run this again.")
            device = os.environ.get("ARES_DEVICE", "tv")
            subprocess.run([ares, "--device", device, path], check=True)
        print("Installed. Now: tools/tv_app.py pair, then tools/tv_app.py open.")
    elif cmd in ("open", "home"):
        tv.open_guest_app()
        print("Opened guest-tv on the TV. The computer opens it again each time the TV comes on"
              " (while server.py runs).")
    elif cmd == "undo":
        if "--remove" in sys.argv:
            if kind == "samsung":
                cli = tool("apps2samsung-cli", "~/Applications/apps2samsung/cli/apps2samsung-cli")
                cli and subprocess.run([cli, "uninstall", "GuestTVApp", "--tv", ip])
            else:
                ares = tool("ares-install")
                ares and subprocess.run([ares, "--device", os.environ.get("ARES_DEVICE", "tv"), "--remove", guest])
        print('To stop the computer opening guest-tv, set "tv_hook": false in data/settings.json and restart server.py.')
    else:
        print(__doc__)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    home_id = arg("--home") or server.settings().get("default_home") or "guest"
    url = arg("--url") or "http://%s:%d" % (lan_ip(), server.PORT)
    if cmd == "build":
        print("Built", os.path.relpath(build(sys.argv[2] if len(sys.argv) > 2 else "", url, home_id), ROOT))
        return
    ip = os.environ.get("TV_IP")
    if not ip:
        raise SystemExit("Set TV_IP to the TV's address, for example: TV_IP=<tv address> .venv/bin/python tools/tv_app.py status")
    kind = os.environ.get("TV_KIND") or server.settings().get("tv_kind") or "android"
    if kind in ("samsung", "lg"):
        return brand_main(cmd, kind, ip, url, home_id)
    tv = tvctl.TV(ip)
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
        if cmd == "home" and is_fire(tv):   # after open_page: its force-stop drops the watcher
            fire_watch(tv, True)
            print("Fire TV: Amazon's home will flash up for a moment after Home, then guest-tv comes back.")
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
        if is_fire(tv):
            fire_watch(tv, False)
            print("Fire TV: the Home button opens Amazon's home again.")
        if "--remove" in sys.argv:
            print(tv.sh("pm uninstall " + APP, 30).strip())
        tv.sh("input keyevent KEYCODE_HOME", 8)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
