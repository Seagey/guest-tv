# guest-tv on a Fire TV running Vega OS (New, Beta)

**New (Beta).** This is the Vega path for Fire TV Stick 4K Select and the newer sticks that run Amazon's
Vega OS. It is written from Amazon's own documentation and checked against a stand in stick on the computer
(`tools/vega_test.py`) so far. First reports from real sticks wanted.

## What guest-tv does on this TV

Vega is not Android: no ADB, no APK, and nothing can replace Amazon's home. So, like Samsung and LG,
guest-tv here is **an app that opens itself, not a true home screen**.

- **The app** (`tv-apps/vega/`) is a tiny Vega app that shows guest-tv's welcome page full screen in
  Amazon's WebView. You build it once with Amazon's free tools.
- **The computer** opens the app when the stick comes on, and carries the Guest remote's keys to the page.
- **Opening the app** uses Amazon's `vega` command if it is installed on the computer, otherwise DIAL.

## What works, and what does not

| | Vega OS |
|---|---|
| Welcome screen | Yes, in the app, once it is built and installed |
| Opens by itself when the stick comes on | Built: a few seconds after the stick joins the network. Whether a sleeping stick leaves the network is not confirmed |
| Phone remote arrows, OK and Back | Yes, **only while guest-tv is on screen** (the keys go to guest-tv's own page, because Amazon documents no key injection) |
| Volume, mute, power off, input | **No.** Those belong to the stick; use its own remote |
| Amazon's Home button | **Still opens Amazon's home.** Home on the Guest remote brings guest-tv back |
| Netflix and YouTube, and a show or video in them | Yes, through DIAL, once the stick's DIAL address is written down (below) |
| Any other app from the phone | **No.** The stick does not list its apps to the network |
| Guest profile picker, screenshots, what is on screen | No. The computer only knows that guest-tv is in front while its page is asking for keys |
| Root, or anything that bypasses Amazon's rules | **Never** |

## Set it up

You need an Amazon Developer account (free as far as we know), a Mac or Linux computer (Amazon does not
support Windows), Amazon's free Vega tools, and a USB cable once. Run the commands below yourself, or give
this page to your AI agent.

1. **Developer Mode on the stick** (Amazon's steps): Settings, My Fire TV, About, press OK on the device
   name seven times, then Developer options, Developer Mode. It shows a 6 digit code: on the computer
   `vega devmode login`, then `vega devmode enable-device --code <code>`.
2. **Network access:** with the USB cable in, `vega exec vda tcpip 5555`. Unplug, find the stick's address
   (Settings, My Fire TV, About, Network) and give it a fixed address in the router. The computer reads
   "the stick is on" from this port being open (`5555`).
3. **Make and install the app:**

   ```sh
   TV_KIND=vega TV_IP=<tv address> .venv/bin/python tools/tv_app.py install
   ```

   It writes the app's address file (`tv-apps/vega/src/guest.json`, never in git, no key in it) and prints
   Amazon's build and install steps, which are also in `tv-apps/vega/README.md`. Run those once.
4. **Tell guest-tv:** `"tv_kind": "vega"` next to the TV's address in `data/settings.json`.
5. **Open it:** `TV_KIND=vega TV_IP=<tv address> .venv/bin/python tools/tv_app.py open`.
6. **Netflix and YouTube titles (optional):** DIAL needs the address of the stick's device description
   (the `LOCATION` a DIAL scan finds). guest-tv never scans the network for it. Write that one line,
   `http://<tv address>:<port>/<path>`, in `data/vega-dial-<tv address>.key`. Without it, Netflix and
   YouTube simply are not offered. Whether DIAL also opens a sideloaded app is not documented, so the
   `vega` command is tried first.

Check what the computer sees: `TV_KIND=vega TV_IP=<tv address> .venv/bin/python tools/tv_app.py status`.
Take it off: `TV_KIND=vega TV_IP=<tv address> .venv/bin/python tools/tv_app.py undo` prints Amazon's remove
command.

## How the Guest remote's keys reach the TV

The TV page asks the computer for keys (a long poll, about every 20 seconds, `keys=1` in its address) and
presses them on itself. The computer treats guest-tv as in front while that poll is recent. If Amazon's
home takes over, the page's polling may carry on for a few seconds, so a key can land on a page nobody is
looking at. Keys nobody collects within 10 seconds are dropped, never replayed.

## Honest limits

- Built once with Amazon's free developer tools, on your own stick. Amazon's Home button still opens
  Amazon's home.
- The app id (`app.guesttv.home.main`) and the manifest lines are our reading of Amazon's templates. Take
  Amazon's generated project as the truth and tell us what differs.
- That the developer port closes when the stick sleeps, and that a sleeping stick can be woken from the
  network, are not confirmed.
- The DIAL payloads for Netflix and YouTube are the apps' own documented formats, never checked on a Vega
  stick. One report said sideloaded Vega apps eventually stop launching: rebuild and reinstall if yours does.
- The phone remote presses arrows, OK and Back only while guest-tv is in front, not volume or power. Only
  Netflix and YouTube open titles from the phone. No Guest profile picker.

## A read only first check

1. `TV_KIND=vega TV_IP=<tv address> .venv/bin/python tools/tv_app.py status` before changing anything.
   A closed port and no `vega` command are both expected before step 2.
2. After the app is installed and open: press the stick's own arrow key, then the phone remote's arrows.
   Do they move the welcome page?
3. Press Amazon's Home on the stick's remote, then Home on the phone remote. Does guest-tv come back?
4. Put the stick to sleep and wake it. Did the welcome screen open by itself?

Say what you see at each step, even when it works. A line is enough. Leave the stick's address out.

## Sources (read November 2026)

- Amazon, Enable Developer Mode (Vega 2.0), Vega CLI tools, VDA over TCP/IP, Develop your app with
  WebView, and DIAL on Vega, on developer.amazon.com/docs/vega.
- couch-tv's `docs/FIRE-VEGA.md`, which this is cut down from.
