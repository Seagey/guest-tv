# guest-tv: notes for the agent setting it up

Read README.md first. This file is what a person's agent needs to finish the setup on their TV.

## Walk the owner through setup

Run `.venv/bin/python setup.py --check` first and fix anything marked FIX. Then ask the owner the
same questions `setup.py` asks, one at a time, in plain words (or let them run `setup.py` themselves):

1. **What kind of place?** A guest room in their home, or a place guests stay in (Airbnb, holiday home).
2. **Which TV?** Its IP address (TV Settings, Network, About). Check it answers over ADB.
3. **What may guests control?** Aircon, lights, anything else. For each: **which rooms** (their room,
   all rooms, or a list). For lights: Home Assistant (best, it covers most brands) or Hue direct.
4. **Which streaming apps are signed in** on that TV (only those are offered to guests).
5. **How much may the agent do?** Read them the three levels from README "Agent levels", with the
   risk column, and let them choose. Recommend Locked. For Open, say plainly: a clever guest can get it
   to do anything the tools you plug in can do. Do not pick Open for them.
6. **Agentic booking** (Open only): set up the browser tool, add `"book"` links to the guide, then run
   `tools/booking_agent_test.py` before any guest uses it.

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
