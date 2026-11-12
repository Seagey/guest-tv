"""Put guest-tv on the TV, and take it off again.

Google TV and Android TV: the couch-tv TV app (couch-tv-home.apk, from
github.com/Seagey/couch-tv/releases) shows a web page full screen and opens the TV's real apps from
it. Here it shows guest-tv instead of couch-tv, and can become the TV's home screen.

    TV_IP=<tv address> .venv/bin/python tools/tv_app.py status            # what is on the TV now
    TV_IP=<tv address> .venv/bin/python tools/tv_app.py install couch-tv-home.apk
    TV_IP=<tv address> .venv/bin/python tools/tv_app.py open [--home guest]  # show guest-tv now
    TV_IP=<tv address> .venv/bin/python tools/tv_app.py home [--home guest] [--watch]  # and make it the TV's home
    TV_IP=<tv address> .venv/bin/python tools/tv_app.py undo [--remove]      # put the old home back

Fire TV (Fire OS 6 and newer, a couch-tv release newer than 0.3): the same commands, and `home` also
switches on the couch-tv app's Home button watch (`undo` switches it off). Google TVs whose own home
ignores the default home (Haier, some Xiaomi and TCL) get the same watch only if the owner chose it
(setup.py's Home button watch question, "home_watch": true, or --watch); on a TCL it also lets the
app start at boot. The TV's own home may flash up for a moment before guest-tv comes back.

Every other TV (TV_KIND, or "tv_kind" in data/settings.json): samsung, lg, roku, vidaa, titan,
saphi, panasonic, vizio, appletv, vega. These TVs let no app replace their home screen, so guest-tv
is an app (or a page in the TV's browser) the computer opens each time the TV comes on.

    .venv/bin/python tools/tv_app.py build <kind> [--home guest]   # pack guest-tv's TV app (build/)
    TV_KIND=<kind> TV_IP=<tv address> .venv/bin/python tools/tv_app.py install
    TV_KIND=<kind> TV_IP=<tv address> .venv/bin/python tools/tv_app.py pair   # Allow on the TV, or its PIN
    TV_KIND=<kind> TV_IP=<tv address> .venv/bin/python tools/tv_app.py open
    TV_KIND=<kind> TV_IP=<tv address> .venv/bin/python tools/tv_app.py undo --remove

`home` writes down the TV's old home first (tvs/<tv address>.home, never in git), and `undo` puts
that one back. `--url http://<this computer's address>:5410` if the guess of this computer's
address is wrong. Nothing here switches off or deletes anything on the TV, except `undo --remove`,
which removes guest-tv's own app.
"""
import importlib, io, json, os, re, shutil, subprocess, sys, tarfile, time, zipfile

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
# Stock homes that outrank the chosen home on the Home key or at power on (as couch-tv's apply.sh).
STOCK_HOMES = (FIRE_HOME, "com.google.android.apps.tv.launcherx", "com.google.android.tvlauncher")
WATCH = (APP + "/.FireWatch", APP + "/" + APP + ".FireWatch")   # how Android may write it down


def is_fire(tv):
    return ("package:" + FIRE_HOME) in tv.sh("pm list packages " + FIRE_HOME, 15)


def has_stock_home(tv):
    out = tv.sh("pm list packages", 20)
    return any(("package:" + p) in out.split() for p in STOCK_HOMES)


def maker(tv):
    """The TV's maker, lower case (TCL needs one more step, couch-tv#94)."""
    return " ".join(tv.sh("getprop ro.product.manufacturer; getprop ro.product.brand", 10).split()).lower()


def watch_listed(tv):
    return any(s in WATCH for s in tv.sh("settings get secure enabled_accessibility_services", 10).strip().split(":"))


def home_watch(tv, on):
    """The couch-tv app's Home button watch (an accessibility service that only sees which window came
    forward) puts guest-tv back on top whenever the TV opens its own home: Fire TV, Google TVs whose
    home outranks the chosen one, and TVs like Haier's whose home ignores the default (couch-tv#98).
    Switched on and off here over ADB. Android drops the watcher whenever the app is stopped or
    updated, so this runs after the app is opened, and the secure-settings grant lets the app put it
    back by itself after updates and reboots. Off takes the grant away first. Already listed: taken
    out and put back, because after a force-stop Android can show it as crashed and never bind it
    again (couch-tv#37)."""
    tv.sh("pm %s %s android.permission.WRITE_SECURE_SETTINGS" % ("grant" if on else "revoke", APP), 10)
    cur = tv.sh("settings get secure enabled_accessibility_services", 10).strip()
    listed = cur.split(":")
    keep = [s for s in listed if s and s != "null" and s not in WATCH and tvctl.COMPONENT_RE.fullmatch(s)]

    def put(items):
        if items:
            tv.sh("settings put secure enabled_accessibility_services '%s'" % ":".join(items), 10)
        else:
            tv.sh("settings delete secure enabled_accessibility_services", 10)
    if on and any(s in WATCH for s in listed):
        put(keep)
        time.sleep(2)
    put(keep + [WATCH[0]] if on else keep)
    if on:
        tv.sh("settings put secure accessibility_enabled 1", 10)


def tcl_boot(tv):
    """TCL's boot manager stops the Home button watch from starting after a restart unless the app may
    start at boot (couch-tv#94: the reporter's confirmed fix is this app op, plus switching the watch
    on once from the TV's own Settings, Accessibility with the remote)."""
    tv.sh("appops set %s AUTO_START allow" % APP, 10)


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
    if not re.fullmatch(r"https?://[\w.:-]+", url) or not re.fullmatch(r"[a-z0-9-]+", home_id):
        raise SystemExit("bad --url or --home")
    tv.page = "%s/tv/?tv=%s&brand=%s" % (url, home_id, kind)
    mod = importlib.import_module(tvbrands.KINDS[kind][0])
    try:
        brand_cmd(cmd, kind, ip, url, home_id, tv, mod)
    except tvbrands.TVUnavailable as e:
        raise SystemExit("The TV says: %s" % e)


def brand_cmd(cmd, kind, ip, url, home_id, tv, mod):
    if cmd == "status":
        if getattr(tv, "paired", True) is False:
            print("Not paired yet: run tools/tv_app.py pair (with TV_KIND and TV_IP) first.")
            return
        on = tv.is_on()
        print("TV answers:", {True: "yes, on", False: "yes, in standby", None: "no"}[on])
        if on:
            if tv.sees_front:
                front = tv.front()
                print("On screen:", front or "nothing (live TV, an input or the TV's menu)")
                if tv.can_open:
                    print("guest-tv on screen:", "yes" if tv.is_guest(front) else "no")
            print("Guest apps found:", ", ".join(a["name"] for a in tv.installed()) or "none")
        if tv.can_open:
            print("guest-tv page for this TV:", tv.page)
        else:
            print("This TV cannot show guest-tv's welcome screen: the Guest remote and the phone side work.")
    elif cmd == "pair":
        if tv.pairing is None:
            print("This TV needs no pairing.")
        elif tv.pairing == "pin":
            if tv.pair_start() is False:
                print("This TV needs no pairing.")
                return
            pin = input("Look at the TV: type the PIN it shows, then Enter: ").strip()
            tv.pair_finish(pin)
            print("Paired. The key is kept in data/ (never in git).")
        else:
            print("Look at the TV: press Allow or Accept. Waiting up to 60 seconds...", flush=True)
            tv.pair(60)
            print("Paired. The key is kept in data/ (never in git).")
    elif cmd == "install":
        if kind in ("samsung", "lg"):
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
                subprocess.run([ares, "--device", os.environ.get("ARES_DEVICE", "tv"), path], check=True)
            print("Installed. Now: tools/tv_app.py pair, then tools/tv_app.py open.")
        elif hasattr(mod, "install"):
            mod.install(ip, url, home_id)
        else:
            setup = getattr(mod, "SETUP", "")
            setup = setup.get(kind, "") if isinstance(setup, dict) else setup
            print(setup or "Nothing to install on this TV: the computer opens guest-tv in the TV's own browser.")
    elif cmd in ("open", "home"):
        if not tv.can_open:
            raise SystemExit("This TV cannot show guest-tv's welcome screen. The Guest remote and the phone side work.")
        tv.open_guest_app()
        print("Opened guest-tv on the TV. The computer opens it again each time the TV comes on"
              " (while server.py runs).")
    elif cmd == "undo":
        if "--remove" in sys.argv:
            if kind == "samsung":
                cli = tool("apps2samsung-cli", "~/Applications/apps2samsung/cli/apps2samsung-cli")
                cli and subprocess.run([cli, "uninstall", "GuestTVApp", "--tv", ip])
            elif kind == "lg":
                ares = tool("ares-install")
                ares and subprocess.run([ares, "--device", os.environ.get("ARES_DEVICE", "tv"), "--remove", tv.guest_id()])
            elif hasattr(mod, "uninstall"):
                mod.uninstall(ip)
        print('To stop the computer opening guest-tv, set "tv_hook": false in data/settings.json and restart server.py.')
    else:
        print(__doc__)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    home_id = arg("--home") or server.settings().get("default_home") or "guest"
    url = arg("--url") or "http://%s:%d" % (lan_ip(), server.PORT)
    if cmd == "build":
        kind = sys.argv[2] if len(sys.argv) > 2 else ""
        if kind in ("samsung", "lg"):
            path = build(kind, url, home_id)
        else:
            import tvbrands
            mod = importlib.import_module(tvbrands.KINDS[kind][0]) if kind in tvbrands.KINDS else None
            if not hasattr(mod, "build"):
                raise SystemExit("build samsung, lg, or a TV whose guest-tv app is built here (roku, appletv, vega)")
            path = mod.build(url, home_id)
        print("Built", os.path.relpath(path, ROOT))
        return
    ip = os.environ.get("TV_IP")
    if not ip:
        raise SystemExit("Set TV_IP to the TV's address, for example: TV_IP=<tv address> .venv/bin/python tools/tv_app.py status")
    kind = os.environ.get("TV_KIND") or server.settings().get("tv_kind") or "android"
    import tvbrands
    if kind in tvbrands.KINDS:
        return brand_main(cmd, kind, ip, url, home_id)
    if kind not in ("android", "fire"):
        raise SystemExit("TV_KIND must be android, fire or one of: " + ", ".join(tvbrands.KINDS))
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
                tvctl.check_component(before)
                os.makedirs(os.path.dirname(saved), exist_ok=True)
                open(saved, "w").write(before + "\n")
                print("Old home written down:", before)
            tv.sh("cmd package set-home-activity " + ACT, 15)
        open_page(tv, url, home_id)
        if cmd == "home":   # after open_page: its force-stop drops the watcher
            # Fire TV always (as before). Any other TV only when the owner chose it: setup.py's Home
            # button watch question ("home_watch": true in data/settings.json) or --watch.
            want = "--watch" in sys.argv or server.settings().get("home_watch") is True
            if is_fire(tv) or want:
                home_watch(tv, True)
                print("Home button watch on: the TV's own home may flash up for a moment after Home, then guest-tv comes back.")
                if not is_fire(tv) and "tcl" in maker(tv):
                    tcl_boot(tv)
                    print("TCL: the app may now start at boot. Once, with the TV remote: Settings, Accessibility (under System\n"
                          "or Device Preferences), switch Home button watch on. That is what keeps guest-tv as the home after a restart.")
            elif has_stock_home(tv) or not (current_home(tv) or "").startswith(APP):
                print("This TV may open its own home after Home or a restart. If it does, run setup.py and say yes to\n"
                      "the Home button watch question (or run this again with --watch).")
        time.sleep(3)
        print("Showing %s/tv/?tv=%s on the TV." % (url, home_id) + (" The Home button now comes back here." if cmd == "home" else ""))
    elif cmd == "undo":
        before = open(saved).read().strip() if os.path.exists(saved) else None
        if before:
            tv.sh("cmd package set-home-activity " + tvctl.check_component(before), 15)
            os.remove(saved)
            print("Home put back:", before)
        else:
            print("No old home written down for this TV. Pick the home in the TV's Settings (Apps, Default apps, Home).")
        if is_fire(tv) or watch_listed(tv):
            home_watch(tv, False)
            print("Home button watch off: the Home button opens the TV's own home again.")
        if "--remove" in sys.argv:
            print(tv.sh("pm uninstall " + APP, 30).strip())
        tv.sh("input keyevent KEYCODE_HOME", 8)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
