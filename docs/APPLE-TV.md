# guest-tv on an Apple TV (New, Beta)

**New (Beta).** Checked against a stand in Apple TV on the computer so far, first reports from real Apple TVs wanted.
Please open an issue and say how it went (the Apple TV model, the tvOS version, what worked and what did not), even
if all of it worked.

On an Apple TV, guest-tv is two parts:

- **Guest TV**, guest-tv's welcome screen as a small Apple TV app (`tv-apps/tvos`). tvOS has no web view, so the web
  page the other TVs show cannot run here. Guest TV draws the same welcome natively: the home's photo, the clock and
  date, the welcome line, the Wi-Fi card with its QR code, the Guest remote card with its QR code, the weather, and the
  door codes when you have set some. You put it on the Apple TV yourself, with Xcode on a Mac and your own Apple ID.
- **The computer talks to the Apple TV** the way the iPhone's Control Centre remote does (Apple's Companion link), so
  the Guest remote's buttons and apps work, and the computer opens Guest TV each time the Apple TV wakes.

Both come from couch-tv's Apple TV work (github.com/Seagey/couch-tv, `bridge/appletv.py` and `tvos/`).

## What works

| | Apple TV |
|---|---|
| Welcome screen on the TV | Yes, Guest TV (needs a Mac with Xcode to put it on, signed again weekly, below) |
| Opens by itself when the Apple TV wakes | Yes, while `server.py` runs. It opens on every wake, because the Apple TV cannot say what is on screen |
| Guest remote: arrows, OK, Back, Play/Pause | Yes |
| Next, previous, fast forward, rewind | Press right or left, which most tvOS players read as a short skip |
| Volume up and down | Yes, when the Apple TV is set to control the TV's volume (HDMI CEC or a learned IR remote, in its Settings) |
| Mute | No: the Companion link has no mute button. The guest gets a plain message |
| Home on the Guest remote | Opens Guest TV |
| Opening an app (Netflix, YouTube, Disney+, Prime Video, Apple TV, Stan and the rest the Apple TV lists) | Yes |
| Opening a show from the guest agent | The app opens on its own home and the guest picks the show there |
| Spotify | Just opens |
| Guest profile picker | No |
| Replacing Apple's home screen | **No, and it cannot be done.** Apple's Home button still opens Apple's home |

## Setup (the owner, or their agent with them)

You need: the Apple TV on tvOS 17 or newer, a Mac with Xcode (free from the App Store) on the same Wi-Fi, an Apple ID
(a free one works), and guest-tv running on a computer that stays on. The Mac that runs guest-tv is the best one for
this, because it also signs Guest TV again every week.

1. **Find the Apple TV.** Its address is in the Apple TV's Settings, Network. Give it a fixed address in your router
   so it never moves. The computer talks to it on a port it announces on the network, usually 49153. To read the port
   (this only listens): `dns-sd -B _companion-link._tcp` lists the Apple TVs by name (Ctrl C to stop), then
   `dns-sd -L "<its name>" _companion-link._tcp` prints `can be reached at <name>.local.:<port>`.
2. **Tell guest-tv.** In `data/settings.json` (or the home's file): `"tv_kind": "appletv"` and `"tv": "<tv address>"`.
   When the port is not 49153, write `"tv": "<tv address>:<port>"`. The port can change after the Apple TV restarts;
   if the remote stops answering, read it again.
3. **Set up Xcode once.** Open Xcode and let it install its components (it asks for the Mac's password). Xcode,
   Settings, Accounts: add your Apple ID. A free one shows as "(Personal Team)"; note the team's id (ten letters and
   numbers).
4. **Pair the Apple TV with Xcode.** On the Apple TV: Settings, Remotes and Devices, Remote App and Devices. On the
   Mac: Xcode, Window, Devices and Simulators. The Apple TV shows up: press Pair and type the code it shows. If either
   asks to turn on Developer Mode, say yes.
5. **Your signing settings.** Copy `tv-apps/tvos/Config/Signing.example.xcconfig` to
   `tv-apps/tvos/Config/Signing.mine.xcconfig`. Put in your team id, and a bundle id that starts with
   `dev.guesttv.appletv.` and ends with something of your own (`dev.guesttv.appletv.smith`), because Apple lets one
   bundle id belong to one person. Git ignores this file, so your team id never goes into the repo.
6. **Put Guest TV on the Apple TV:**

   ```
   TV_KIND=appletv TV_IP=<tv address> .venv/bin/python tools/tv_app.py install
   ```

   It writes where Guest TV finds this computer (`build/tvos/Home.xcconfig`), builds Guest TV, signs it with your Apple
   ID, installs it on the Apple TV and opens it. The first time, if the Apple TV says the developer is not trusted,
   trust your Apple ID once in the Apple TV's Settings (under General, the menu's name changes between tvOS versions).
   When Xcode knows more than one Apple TV, set `APPLETV_NAME=<part of its name>`.
7. **Pair guest-tv with the Apple TV** (for the Guest remote and the hook). Wake the Apple TV, then:

   ```
   TV_KIND=appletv TV_IP=<tv address> .venv/bin/python tools/tv_app.py pair
   ```

   The Apple TV shows a 4 digit PIN: type it. The keys are kept in `data/` (git ignored, readable only by you). The
   Apple TV now lists this computer under Settings, Remotes and Devices, and you can remove it there.
8. **Show it:** `TV_KIND=appletv TV_IP=<tv address> .venv/bin/python tools/tv_app.py open`, then restart `server.py`
   so it opens Guest TV each time the Apple TV wakes. Put Guest TV in the top row of Apple's home so it is one click
   away from there too.
9. **Keep it signed** (next section).

If the computer's address changes, run `install` again: the address is built into Guest TV. Give the computer a fixed
address in the router too.

### Keep it signed (twice a week)

Apple makes a free Apple ID signature run out after 7 days. `tools/appletv-resign.sh` builds, signs and installs Guest
TV again; run it from launchd on the Mac twice a week. Save this as
`~/Library/LaunchAgents/guesttv.appletv-resign.plist`, with the path to your guest-tv folder in it, then
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/guesttv.appletv-resign.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>guesttv.appletv-resign</string>
  <key>ProgramArguments</key>
  <array><string>/bin/sh</string><string>/path/to/guest-tv/tools/appletv-resign.sh</string></array>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>3</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>3</integer><key>Minute</key><integer>30</integer></dict>
  </array>
</dict>
</plist>
```

Each run writes one line to `build/appletv-resign.log` saying it worked or why it stopped (the Apple TV was off, Xcode
was signed out). A missed run is fixed by the next one, as long as it comes within the 7 days. If the Mac is off for
longer, Guest TV stops opening until the script runs again; the Guest remote is not affected. Stop the job with
`launchctl bootout gui/$(id -u)/guesttv.appletv-resign`.

With the paid Apple Developer Program (US$99 a year) the signature lasts a year instead: put the paid team's id in
`Signing.mine.xcconfig` and run the script once a year. Nothing else in guest-tv needs it.

## First check (read only)

```
TV_KIND=appletv TV_IP=<tv address> .venv/bin/python tools/tv_app.py status
```

It says whether the Apple TV answers and whether it is awake or asleep, and lists the guest apps it found. It changes
nothing. Before pairing it cannot read anything (the Apple TV only answers a paired computer), so pair first.

## Take it off again

```
TV_KIND=appletv TV_IP=<tv address> .venv/bin/python tools/tv_app.py undo --remove
```

removes Guest TV from the Apple TV. Then stop the weekly job (`launchctl bootout`, above), remove this computer in the
Apple TV's Settings, Remotes and Devices, and set `"tv_hook": false` in `data/settings.json` (or remove the Apple TV
from it) and restart `server.py`.

## How it works

- **The welcome screen.** Guest TV asks the computer for `/api/tv/native?home=<home>` every 60 seconds and draws it,
  with the photo and the two QR codes the computer names. It only asks that one computer, and only reads. While the
  computer does not answer, it keeps the last screen and says "Waiting for the house computer"; before the first
  answer it shows the clock and that message. The Wi-Fi and the door codes follow the same rules as the web page:
  only while a stay shows them.
- **The remote.** The computer pairs once with the PIN, then every connection is checked and sealed with keys made on
  the computer. Nothing of Apple's is included. Only a fixed table of buttons and the bundle ids of the guest apps go
  to the Apple TV; nothing a guest types does.
- **The hook.** The computer reads every two seconds whether the Apple TV is awake or asleep. When it wakes, the
  computer opens Guest TV, unless a guest's own command ran in the last 20 seconds. Waking from the screensaver does not
  count, so a paused show is left alone.

## Limits, plainly

- **Apple's Home button still opens Apple's home.** tvOS lets no app replace it. Guest TV opens when the Apple TV wakes
  (with `server.py` running) and from Home on the Guest remote.
- **The free signing needs a Mac and is redone weekly by the computer.** If that Mac is off for more than 7 days,
  Guest TV stops opening until the script runs again.
- **No Guest profile picker**, no screenshots, no "what is on screen", no mute, no typing from the phone.
- **Spotify just opens**, and other apps open on their own home, not inside a show.
- **The volume buttons** only reach the TV when the Apple TV is set to control it.
- **The Companion port can change** after the Apple TV restarts (step 1 finds it again).
- **Settings, AirPlay and HomeKit, Allow access** on the Apple TV can limit which devices may control it. "Anyone on
  the same network" is the setting that works with this.

## Test status

- `tools/appletv_test.py` runs the driver (`tv_appletv.py`) against a stand in Apple TV on the computer, written from
  the same public protocol notes as the driver: the binary formats, pairing with the right PIN, a wrong PIN and a PIN
  that is not 4 digits, a reset Apple TV, awake, screensaver, asleep and gone, a dropped connection, the app list and
  an unsafe id from the Apple TV, every guest key, volume, mute, shows, opening Guest TV, and the hook (opens on wake,
  leaves an app alone, waking from the screensaver, a guest's quiet time, a short Wi-Fi dropout).
- Guest TV builds with Xcode for the tvOS Simulator and, unsigned, for a real Apple TV. Its screen was drawn on a Mac
  from its own SwiftUI code against a stand in computer (`tv-apps/tvos/preview/render.sh`).
- The likeliest places for a surprise on a real Apple TV, from couch-tv's notes: the pairing messages, the first
  messages after pairing, whether the screensaver shows as its own state, the port, and the bundle ids in the table.

## For developers

- `tv-apps/tvos/make-project.py` writes the Xcode project and `tv-apps/tvos/make-assets.py` the icons. Run them after
  adding a Swift file or changing the look. The fonts are couch-tv's (Inter and Antonio).
- `.venv/bin/python tv-apps/tvos/preview/standin.py 5419` runs a stand in computer on 127.0.0.1, and
  `tv-apps/tvos/preview/render.sh http://127.0.0.1:5419 build/tvos-preview lake plain` draws Guest TV's screen to
  PNG files from its own SwiftUI code (no blur behind the glass there).
- In the tvOS Simulator: build with `GUESTTV_HOST=127.0.0.1:5419` set in Xcode's build settings (or in
  `build/tvos/Home.xcconfig`) and run the stand in.

## Sources

- The Companion link and pairing: couch-tv's `bridge/appletv.py`, written from the public protocol notes at
  <https://pyatv.dev/documentation/protocols/> (couch-tv's code is its own, and so is this).
- tvOS has no web view: <https://developer.apple.com/documentation/tvml> (TVML, deprecated in tvOS 18, was the only
  web style option).
- Free Apple ID signing lasts 7 days, a paid account 12 months; installing from the command line with
  `xcrun devicectl device install app` (Xcode 15 and newer).
