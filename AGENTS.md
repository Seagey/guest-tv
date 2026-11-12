# guest-tv: notes for the agent setting it up

Read README.md first. This file is what a person's agent needs to finish the setup on their TV.

## Walk the owner through setup

The quickest path is README "The quick way": `sh scripts/start.sh` on the computer, then the Guest
TV app on a Google TV, Android TV or Fire TV through Downloader (the code `1061533`, or the short link
`couchtv.sites.underseage.studio/guest`), with no ADB. Offer it first for those
TVs; the ADB steps below remain for owners who want them. Run `.venv/bin/python setup.py --check` first and fix anything marked FIX. Then ask the owner the
same questions `setup.py` asks, one at a time, in plain words (or let them run `setup.py` themselves):

1. **What kind of place?** A guest room in their home, or a place guests stay in (Airbnb, holiday home).
2. **Which TV?** Its kind and its IP address (TV Settings, Network, About). Google TV, Android TV
   or Fire OS: check it answers over ADB. Samsung or LG: README "Samsung and LG". Roku, Hisense VIDAA,
   Philips (Titan OS or Saphi), Panasonic, VIZIO, Apple TV or Fire TV on Vega OS: README "Every other
   TV" and that TV's page in `docs/`. Brands that sell more than one system (Hisense, Philips,
   Panasonic, Sharp): "Android TV OS" in Settings, About means the Google TV path. Say the TV's honest
   limits from README "Will it work on my TV?" before going on (VIZIO: no welcome screen at all).
3. **What may guests control?** Aircon, lights, anything else. For each: **which rooms** (their room,
   all rooms, or a list). For lights: Home Assistant (best, it covers most brands) or Hue direct.
4. **Which streaming apps are signed in** on that TV (only those are offered to guests).
5. **How much may the agent do?** Read them the three levels from README "Agent levels", with the
   risk column, and let them choose. Recommend Locked. For Open, say plainly: a clever guest can get it
   to do anything the tools you plug in can do. Do not pick Open for them.
6. **Agentic booking** (Open only): set up the browser tool, add `"book"` links to the guide, then run
   `tools/booking_agent_test.py` before any guest uses it.
7. **Put it on the TV** with `tools/tv_app.py`: `status` first, then `install couch-tv-home.apk` (the
   owner downloads it from github.com/Seagey/couch-tv/releases), then `home --home <id>`. Tell the
   owner that `tools/tv_app.py undo` puts their old home screen back. The Home button watch on a TV
   that is not a Fire TV is optional: only if the owner says the TV goes back to its own home after
   Home or a restart (setup.py asks; never switch it on for them). On a **TCL** with the watch, after `home`, walk
   the owner through switching **Home button watch** on in the TV's own Settings, Accessibility with
   the remote (couch-tv#94: that, with the boot permission `home` sets, keeps guest-tv as the home
   after a restart). If the services are missing from that menu, open the app once and look again.
   Any other TV: `status` first (reads only), then `install`, `pair` (the owner presses Allow, or
   reads you the PIN the TV shows), `open`, with `TV_KIND` set. The Samsung install opens a browser
   for the owner's Samsung sign-in.

Before you finish, say the must-haves out loud: everything on one Wi-Fi, the computer never sleeps,
Claude Code stays signed in.

## Ask the owner, never do it yourself

- **Signing in** to streaming apps, Wi-Fi or any account. If an app offers saved sign-ins (Google's
  "Choose an account" box), press Cancel and tell the owner.
- **Which profile becomes the guest one** when an app is full. Ask; renaming changes their account.
- **Wi-Fi password and door codes.** They type them in (host panel or `data/private.json`).
  Never read them from the computer's keychain.
- **Mute the TV before testing**, every time, and check it (`dumpsys audio`, look for `Muted: true`).

## Guest remote and guest agent (guest_agent.py, tvctl.py)

- **Never give the guest agent tools, MCP servers, files or web access**, and never let text from a
  guest reach a shell command. New abilities go in as a new action in `check()` and `run()`, built
  from fixed tables in `tvctl.py`. That code check is the guard rail, not the prompt.
- After any change to `guest_agent.py`, run `tools/agent_test.py`. Both sets must pass 30 of 30.
- After any change to `server.py`, run `tools/security_test.py` (JSON only POSTs, the Host check, the
  wrong code limit, package checks; no TV, no AI).
- Mute the TV before testing. The first real aircon change on a new setup is done with the owner
  watching.
- Spotify's TV app ignores links and hides its screen from ADB: `tvctl.spotify` walks its Search
  page by keys. If a Spotify update moves the Search button, re-check the key steps with screenshots.

## Levels, lights and booking (devices.py, guest_agent.py)

- New abilities go in as a new action in `check()` and `run()`, or as an owner action in
  `data/actions.json`. Never widen what the Locked level can do.
- Open level tools: only `WebSearch`, `WebFetch` and the MCP servers the owner listed. `call_claude`
  always disallows Bash, Read, Write and Edit. Keep it that way.
- Agentic booking must always show the guest a confirm card first, and the booking run must only get
  the checked fields, never the guest's own words.
- Test booking only against `tools/booking-samples/fake_restaurant.py`. Never make a real booking to
  test, and never at a real restaurant without the owner asking.
- After changing lights or actions, run `tools/devices_test.py` (no AI, a few seconds).

## Every TV that is not Android (tvbrands.py, tv_<kind>.py, tv-apps/, docs/)

- Same calls as `tvctl.TV`, so `guest_agent.py` and the remote need no change. Samsung and LG are in
  `tvbrands.py`; each other TV is one self contained driver (`tv_roku.py`, `tv_vidaa.py`,
  `tv_philips.py`, `tv_panasonic.py`, `tv_vizio.py`, `tv_appletv.py`, `tv_vega.py`) registered in
  `tvbrands.KINDS`. A new key or app goes in the fixed tables at the top of the driver, never as
  text from a guest. Any id the TV lists is checked against a strict pattern before it goes back.
- After any change, run that TV's test: `tools/brands_test.py` (Samsung, LG), `tools/<kind>_test.py`
  (roku, vidaa, philips, panasonic, vizio, appletv, vega) and `tools/security_test.py`. All of them
  run stand-in TVs on 127.0.0.1 only. No AI.
- Never pair, install or test on a real TV without the owner at it, and mute it first. Never scan the
  network for TVs. `tools/tvui.py` refuses to run unless `GUEST_TV_REAL_TV=1`: only set that with the
  owner's yes, for the one command.
- A TV that already has another app opening itself (couch-tv's hook): set `"tv_hook": false` for that
  TV, or the two hooks fight over the screen. On a Roku, installing guest-tv's channel replaces any
  other sideloaded channel (couch-tv's included): say so first.
- Secrets the owner supplies (a Hisense client certificate in `data/vidaa/`, Philips's pairing key,
  an Apple ID for signing) are never shipped, fetched, printed or logged. Ask the owner to put them in
  place themselves. Tokens live in `data/*.key` (git ignored).
- Per TV, what to tell the owner and what never to do:
  - **Roku:** Developer Mode (Home three times, Up twice, Right, Left, Right, Left, Right) and a
    password the owner makes up, typed by them (`ROKU_DEV_PASSWORD` or the prompt, never stored).
    "Control by mobile apps" must be Permissive or Enabled, or the Roku refuses the remote.
  - **Hisense VIDAA:** `pair` shows a 4 digit PIN on the TV. Newer firmware needs the owner's own
    client certificate in `data/vidaa/client.pem` and `client.key`. VIDAA's Home button cannot be
    taken over, and guest-tv never roots a TV.
  - **Philips:** `TV_KIND=titan` or `saphi`. Titan pairing needs the owner's own Philips key, saved by
    them with `python tv_philips.py secret`; never fetch it or suggest a source. Titan's welcome screen
    needs a Guest TV DevView app the owner makes; without it only the Guest remote works. Never send
    `activities/browser` before the owner says yes, and never use the TV's developer debug port.
  - **Panasonic:** `pair` only on 2018 and newer sets (a PIN on the TV). The TV cannot say what is on
    screen, so never tell a guest the page is confirmed open. Panasonic's Google TV models are Android TVs.
  - **VIZIO:** `pair` shows a 4 digit PIN; there is no `install`. Guest remote only: never promise
    the welcome screen, the profile picker or typing. VIZIO's app list is for the US, Canada and Mexico.
  - **Apple TV:** `pair` shows a PIN on the Apple TV. Guest TV is built with Xcode on a Mac and signed
    with the owner's own Apple ID (`tv-apps/tvos/Config/Signing.mine.xcconfig` copied from `Signing.example.xcconfig`, git ignored, written by the
    owner); free signing lasts 7 days, so `tools/appletv-resign.sh` runs weekly. Never put an Apple ID
    or team id in the repo.
  - **Fire TV on Vega OS:** the owner builds the app once with Amazon's free tools (`install` prints
    the steps and writes the git ignored `tv-apps/vega/src/guest.json`). Phone keys work only while
    guest-tv is in front, and never volume, power or Home. Never run SSDP or scan for the stick.

## Booking emails (bookings.py)

- The owner makes the mailbox app password and types it into `data/private.json` themselves.
- Before trusting it, run the owner's first real Airbnb booking email through `bookings.parse` and
  compare with what the email says. The patterns were written on 2 Nov 2026 from sample emails only.
- Guest names never go in the repo: they live in `private.json` and `data/bookings-inbox/` (both git ignored).

## Guest profiles (profiles.py)

`profiles.py` runs inside `server.py` when `data/settings.json` has a `profiles` block. Every 2.5 s it
asks the TV which app is on screen. When a streaming app opens it reads the screen for up to 30 s and,
on a "Who's watching?" screen, presses the profile named in `profiles.names` (Guest by default). It
presses nothing else, and does nothing when there is no guest profile.

Setting up a new TV:

1. ADB on (Developer options, USB debugging), the owner presses Allow once.
2. Set `profiles.tv` to the TV's IP address. Not its `.local` name: two Android devices on one Wi-Fi can
   get the same `.local` name, and then the name can move to the other device (we saw a TV's name move to the aircon).
3. The owner signs in to each app and adds a **Guest** profile.
4. Open each app with `tools/tvui.py open <package>`, wait about 20 s, run `tools/tvui.py ui`, and
   read `GET /api/profiles`. You want `picked Guest`.

What we saw per app (TCL Android TV 11, Oct 2026):

| App | Package | Screen readable? | Notes |
|---|---|---|---|
| Stan | `au.com.stan.and` | Yes | A tap only moves the focus; OK presses. profiles.py handles it. Max 5 profiles. |
| Netflix | `com.netflix.ninja` | No (blank dump and screenshot) | Use `profiles.blind` with the guest profile's position. Ask the owner which place it is. |
| Disney+ | `com.disney.disneyplus` | Not tested (signed out) | |
| Prime Video | `com.amazon.amazonvideo.livingroom` | Not tested (signed out) | |
| YouTube | `com.google.android.youtube.tv` | n/a | Google accounts, not profiles |

## Stepping through a TV by hand

`tools/tvui.py` (run with a Python that has `adb-shell` and `rsa`, `TV_IP=<address>`):
`open <pkg>`, `ui` (labels with `*` on the focused one and `@x,y`), `shot out.png`,
`key DPAD_CENTER BACK ...`, `tap X Y`, `text WORD`, `stop <pkg>`.

On-screen keyboards in apps (Stan) also take a tap as "move focus": tap a key, then `key DPAD_CENTER`.
Before pressing anything near a "Delete" button, read the screen again and check where the focus is.

## Keep the website in step

guest-tv has a website for hosts. Its setup steps, its "Will it work on my TV?" check, its limits and
its FAQ are taken from this README, this file and `docs/`. Whenever you change any of those (a setup
step, the TV table, a limit, a new feature, the Downloader code or short link), say so in the commit
or pull request, so the website is updated in the same job and the two never disagree.
