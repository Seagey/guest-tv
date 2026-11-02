#!/usr/bin/env python3
"""Set up guest-tv by answering questions. Writes data/settings.json and your home in data/private.json.

    .venv/bin/python setup.py           # the questions
    .venv/bin/python setup.py --check   # only check the must-haves

Run it again any time to change an answer. Nothing is sent anywhere: it only talks to your TV,
your aircon and your lights on your own Wi-Fi.
"""
import getpass, json, os, platform, re, shutil, subprocess, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DATA = os.path.join(HERE, "data")
PLAYWRIGHT_MCP = "@playwright/mcp@0.0.84"   # the browser tool for agentic booking, pinned


def jread(p, d=None):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return d


def jwrite(p, obj):
    with open(p + ".tmp", "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(p + ".tmp", p)


def say(t=""):
    print(t)


def ask(q, default=None, secret=False):
    hint = " [%s]" % default if default not in (None, "") and not secret else ""
    v = (getpass.getpass(q + ": ") if secret else input(q + hint + ": ")).strip()
    return v or (default or "")


def pick(q, options, default=1):
    say("\n" + q)
    for i, (label, note) in enumerate(options, 1):
        say("  %d. %s%s" % (i, label, ("\n     " + note) if note else ""))
    while True:
        v = ask("Pick a number", str(default))
        if v.isdigit() and 1 <= int(v) <= len(options):
            return int(v) - 1


def yes(q, default=True):
    v = ask(q + (" (Y/n)" if default else " (y/N)"), "").lower()
    return default if not v else v.startswith("y")


def http(method, url, body=None, headers=None):
    req = urllib.request.Request(url, json.dumps(body).encode() if body is not None else None,
                                 dict({"content-type": "application/json"}, **(headers or {})), method=method)
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read() or b"{}")


# ---------------------------------------------------------------- must-haves

def checks(tv_ip=None):
    say("\nThe must-haves")
    say("--------------")
    good = True

    def line(ok, text, fix=""):
        nonlocal good
        good = good and ok
        say(("  OK   " if ok else "  FIX  ") + text + ("" if ok or not fix else "\n         " + fix))

    say("  INFO The TV, the aircon, the lights, this computer and the guest's phone must all be on the\n"
        "       same Wi-Fi. The Guest remote only works on your Wi-Fi.")
    try:
        st = json.loads(subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, timeout=20).stdout or "{}")
        line(bool(st.get("loggedIn")), "Claude Code is signed in on this computer", "Install Claude Code, then run: claude  (and sign in)")
    except Exception:
        line(False, "Claude Code is installed", "Install it: https://code.claude.com, then sign in")
    if platform.system() == "Darwin":
        out = subprocess.run(["pmset", "-g"], capture_output=True, text=True).stdout
        m = re.search(r"^\s*sleep\s+(\d+)", out, re.M)
        line(bool(m) and m.group(1) == "0", "This computer never goes to sleep (it runs the TV, the remote and the agent)",
             "System Settings > Energy: turn on 'Prevent automatic sleeping', or run: sudo pmset -a sleep 0")
    else:
        say("  INFO This computer must stay on and never sleep. It runs the TV page, the remote and the agent.")
    for mod, pkg in (("segno", "segno"), ("adb_shell", "adb-shell"), ("rsa", "rsa")):
        try:
            __import__(mod)
            line(True, "Python package %s" % pkg)
        except ImportError:
            line(False, "Python package %s" % pkg, ".venv/bin/pip install %s" % pkg)
    key = os.path.expanduser("~/.android/adbkey")
    if not os.path.isfile(key):
        try:   # the key the TV is asked to trust; the same one adb itself would make
            from adb_shell.auth.keygen import keygen
            os.makedirs(os.path.dirname(key), exist_ok=True)
            keygen(key)
            line(True, "Made an ADB key for this computer (~/.android/adbkey)")
        except Exception:
            line(False, "An ADB key on this computer", "Install Android platform tools and run: adb devices  (once makes the key)")
    else:
        line(True, "ADB key on this computer")
    if tv_ip:
        try:
            import tvctl
            say("  ...   Connecting to the TV. If it asks \"Allow debugging?\", tick Always allow and press OK (60 s).")
            line("ok" in tvctl.TV(tv_ip, auth_timeout=60).sh("echo ok", 10), "The TV at %s answers over ADB" % tv_ip)
        except Exception as e:
            line(False, "The TV at %s answers over ADB (%s)" % (tv_ip, type(e).__name__),
                 "On the TV: Settings > System > About, press Build 7 times, then Developer options > USB debugging on.\n"
                 "         Then run this again and press Allow on the TV.")
    return good


# ---------------------------------------------------------------- the questions

def lights_setup(rooms):
    kind = pick("Which smart lights?", [
        ("Home Assistant", "Covers Hue, LIFX, TP-Link, Govee, Nanoleaf and most others. Best choice if you have it."),
        ("Philips Hue (no Home Assistant)", "Talks to the Hue bridge on your Wi-Fi."),
        ("Skip lights", "")])
    if kind == 2:
        return None, {}
    pv = {}
    if kind == 0:
        url = ask("Home Assistant address", "http://homeassistant.local:8123").rstrip("/")
        say("In Home Assistant: your profile > Security > Long-lived access tokens > Create token. Paste it here.")
        pv["ha_token"] = ask("Token (hidden)", secret=True)
        try:
            states = http("GET", url + "/api/states", headers={"authorization": "Bearer " + pv["ha_token"]})
            found = [(s["entity_id"], (s.get("attributes") or {}).get("friendly_name", "")) for s in states if s["entity_id"].startswith("light.")]
        except Exception as e:
            say("Couldn't reach Home Assistant (%s). Check the address and token, then run setup again." % type(e).__name__)
            return None, {}
        cfg = {"kind": "home_assistant", "url": url}
    else:
        bridge = ask("Hue bridge IP address (Hue app > Settings > Bridges > i)")
        input("Press the round button on top of the Hue bridge, then press Enter here within 30 seconds.")
        try:
            r = http("POST", "http://%s/api" % bridge, {"devicetype": "guest-tv#setup"})
            pv["hue_user"] = r[0]["success"]["username"]
            lights = http("GET", "http://%s/api/%s/lights" % (bridge, pv["hue_user"]))
            found = [(k, v.get("name", "")) for k, v in lights.items()]
        except Exception:
            say("The bridge didn't give a key. Press its button and run setup again.")
            return None, {}
        cfg = {"kind": "hue", "bridge": bridge}
    if not found:
        say("No lights found.")
        return None, pv
    say("\nLights found:")
    for i, (lid, name) in enumerate(found, 1):
        say("  %d. %s  (%s)" % (i, name or lid, lid))
    cfg["rooms"] = {}
    for room in rooms:
        v = ask("Which lights are in %s? Numbers with commas, or Enter for none" % room, "")
        ids = [found[int(x) - 1][0] for x in re.findall(r"\d+", v) if 1 <= int(x) <= len(found)]
        if ids:
            cfg["rooms"][room] = ids
    return cfg, pv


def scope(what, rooms, mine):
    i = pick("Which rooms' %s may guests control?" % what, [
        ("Only their room (%s)" % mine if mine else "Only their room", "Best for a guest room in your own home."),
        ("All rooms", "Best when guests have the whole place."),
        ("Pick rooms", ""), ("None", "")], 2 if len(rooms) > 1 and mine is None else 1)
    if i == 0:
        return "their room"
    if i == 1:
        return "all"
    if i == 3:
        return "none"
    v = ask("Room names, with commas (%s)" % ", ".join(rooms))
    return [x.strip() for x in v.split(",") if x.strip()]


def agent_level(old):
    say("\nHow much may the guest agent do?")
    say("--------------------------------")
    say("Guests type requests into the Ask box on their phone. Whatever the agent can do, a guest can\n"
        "try to talk it into. Give it as much as you are comfortable with a stranger asking for.")
    i = pick("Agent level", [
        ("Locked (recommended)", "Only the TV, music and the devices you picked above, plus answers about the weather and\n"
         "     your area. It has no tools: it picks from a short menu and the code checks every pick.\n"
         "     A guest can't talk it into anything else. Dinner answers get a Book a table button\n"
         "     that opens the restaurant's own booking page, and the guest books it themselves."),
        ("Plus", "Locked, plus buttons you add yourself in data/actions.json (a webhook or a Home Assistant\n"
         "     script: the pool heater, the outdoor lights, a booking request to your favourite restaurant).\n"
         "     Still checked by code. Only add what you'd let any guest press."),
        ("Open (read the warning)", "The agent also gets web search, and any tools you plug in (MCP servers). It can\n"
         "     book a table for the guest by filling in the restaurant's booking page in a browser.\n"
         "     WARNING: a clever guest can get it to do anything those tools can do, and it uses more\n"
         "     of your Claude plan. Only plug in tools you'd hand to a stranger.")],
        {"locked": 1, "plus": 2, "open": 3}.get(old.get("level"), 1))
    ag = {"level": ("locked", "plus", "open")[i]}
    if i >= 1:
        ex = os.path.join(DATA, "actions.json")
        if not os.path.isfile(ex):
            shutil.copy(os.path.join(DATA, "actions.example.json"), ex)
            say("Made data/actions.json from the example. Edit it to add your own buttons.")
    if i == 2:
        if ask("Type OPEN to confirm you've read the warning") != "OPEN":
            say("Kept it on Plus.")
            ag["level"] = "plus"
            return ag
        ag["open"] = {"web": yes("Let it search the web for local answers (opening hours, events, show times)?")}
        if yes("Let it book tables for guests (agentic booking)?"):
            if not shutil.which("npx"):
                say("Booking needs Node.js (npx). Install it from nodejs.org, then run setup again.")
            else:
                chrome = yes("Is Google Chrome installed on this computer?")
                args = ["-y", PLAYWRIGHT_MCP, "--headless", "--isolated"] + (["--browser", "chrome"] if chrome else [])
                jwrite(os.path.join(DATA, "booking-mcp.json"), {"mcpServers": {"browser": {"command": "npx", "args": args}}})
                ag["booking"] = {"mcp_file": "booking-mcp.json", "allowed_tools": ["mcp__browser"]}
                say("Booking is on. It uses the booking page link on each place in your house guide (\"book\").\n"
                    "It never pays, never enters a card and never makes an account. If a booking needs any of\n"
                    "those, the guest gets the booking page instead.")
                if not chrome:
                    say("Run once to get the browser: npx playwright install chromium")
    return ag


def main():
    if "--check" in sys.argv:
        st = jread(os.path.join(DATA, "settings.json"), {}) or {}
        sys.exit(0 if checks(st.get("tv")) else 1)
    st = jread(os.path.join(DATA, "settings.json"), {}) or {}
    pv = jread(os.path.join(DATA, "private.json"), {}) or {}
    say("guest-tv setup\n==============")
    kind = pick("What kind of place is this?", [
        ("A guest room in my home", "Friends and family. No check-in, check-out or house rules on screen."),
        ("A place guests stay in (Airbnb, holiday home)", "Their name, dates, door codes during the stay, check-out steps.")])
    hid = "guest" if kind == 0 else ask("A short id for this home (letters only)", "myplace").lower()
    hid = re.sub(r"[^a-z0-9-]", "", hid) or "myplace"
    home = pv.setdefault("homes", {}).setdefault(hid, {})
    if kind == 1 and not os.path.isfile(os.path.join(DATA, "homes", hid, "home.json")):
        os.makedirs(os.path.join(DATA, "homes", hid), exist_ok=True)
        base = jread(os.path.join(DATA, "homes", "lake", "home.json"), {})
        base.update(id=hid, name=ask("The home's name", "My place"), demo=False, mode="stay")
        for k in ("demo_stay", "lights", "control"):
            base.pop(k, None)
        jwrite(os.path.join(DATA, "homes", hid, "home.json"), base)
    home["host"] = ask("Your first name(s), shown as 'Staying with ...'", home.get("host", ""))
    wifi = home.get("wifi") or {}
    say("\nThe guest Wi-Fi (shown on the TV with a join code, so use a guest network if you have one).")
    home["wifi"] = {"ssid": ask("Wi-Fi name", wifi.get("ssid", "")), "password": ask("Wi-Fi password", wifi.get("password", ""))}
    if kind == 1:
        say("\nAirbnb calendar link (Airbnb: Calendar, Availability, Connect calendars, Export). Enter to skip.")
        cal = ask("Calendar link", home.get("calendar_url", ""))
        if cal:
            home["calendar_url"] = cal
    st["tv"] = ask("The TV's IP address (TV Settings > Network > About)", st.get("tv", ""))
    st.setdefault("default_home", hid)

    say("\nWhat may guests control?")
    say("------------------------")
    say("The TV is always on the list. Pick the rest.")
    rooms = [x.strip() for x in ask("Room names in your home, with commas (e.g. Bed 3, Living)", ", ".join(
        sorted(set((home.get("climate") or {}).get("zones", [])) | set(((home.get("lights") or {}).get("rooms") or {}).keys())))).split(",") if x.strip()]
    mine = None
    if kind == 0 and rooms:
        mine = ask("Which room do guests sleep in?", home.get("room") or rooms[0])
        home["room"] = mine
    control = {}
    if yes("\nAirconditioning? (AirTouch 5 is supported)", bool(st.get("aircon"))):
        st["aircon"] = dict(st.get("aircon") or {}, kind="airtouch5")
        ip = ask("AirTouch console IP (Enter to find it on the Wi-Fi)", (st["aircon"] or {}).get("ip", ""))
        if ip:
            st["aircon"]["ip"] = ip
        st["aircon"]["write"] = yes("Let guests actually change it? (No = preview only, for testing)", True)
        home["climate"] = dict(home.get("climate") or {}, zones=rooms)
        control["aircon"] = scope("aircon", rooms, mine)
    else:
        control["aircon"] = "none"
    if yes("\nSmart lights?", bool(home.get("lights"))):
        cfg, keys = lights_setup(rooms)
        pv.update(keys)
        if cfg:
            home["lights"] = cfg
            control["lights"] = scope("lights", list(cfg["rooms"]), mine if mine in cfg["rooms"] else None)
    home["control"] = control
    say("\nStreaming apps: only list the ones signed in on this TV, so a guest never lands on a login screen.")
    say("Give each one a profile called Guest (README, 'Guest profiles').")
    st["guest_apps"] = [x.strip() for x in ask("App ids, with commas (stan, netflix, disney-plus, prime-video, youtube, spotify ...)",
                                                ", ".join(st.get("guest_apps") or ["youtube"])).split(",") if x.strip()]
    st["agent"] = agent_level(st.get("agent") or {})

    jwrite(os.path.join(DATA, "settings.json"), st)
    jwrite(os.path.join(DATA, "private.json"), pv)
    say("\nSaved data/settings.json and data/private.json.")
    checks(st.get("tv"))
    tv = st.get("tv") or "<tv address>"
    say("\nNext (README, Setup steps 4 to 6):\n  1. Start it: .venv/bin/python server.py  (keep it running: service/)\n"
        "  2. Put it on the TV: TV_IP=%s .venv/bin/python tools/tv_app.py install couch-tv-home.apk\n"
        "                       TV_IP=%s .venv/bin/python tools/tv_app.py home --home %s\n"
        "  3. Scan the Guest remote code on the TV with your phone and try the Ask box.\n"
        "  4. Test the agent's guard rails: .venv/bin/python tools/agent_test.py" % (tv, tv, hid))


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. Nothing more was saved.")
