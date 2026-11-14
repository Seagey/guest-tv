# guest-tv: the agentic guest TV

A welcome screen for guests on your TV, and a **Guest remote** on their phone with an AI agent
built in. Guests scan a code and can control the TV, run the aircon and lights in their room, put
music on, ask what to watch, check the weather, and find (and book) somewhere for dinner. The agent
is locked down, so a guest can't talk it into anything you haven't allowed. Open source (MIT).
Built with Claude.

![The TV and the Guest remote](docs/screens/hero.jpg)

**Quickest setup:** one command on a computer that stays on, then the Guest TV app on the TV, typed
in with the TV remote. No AI and no developer settings needed on a Google TV, Android TV or Fire TV:
[The quick way](#the-quick-way). An AI agent can do it all for you instead: [Setting it up with an AI agent](#setting-it-up-with-an-ai-agent).

## What guests see

Two layouts, one setup. A **guest room** for friends and family: welcome, Wi-Fi, their room, the
weather and local picks, with no check-in, check-out or house rules. A **stay** for an Airbnb or a
holiday home: the guest's name (read from the Airbnb booking email), their dates, the door code only
during the stay, house rules and the check-out steps. The screen changes with each moment of a stay.

| Guest room | Arrival day | During the stay |
|---|---|---|
| ![Guest room](docs/screens/tv-guest-room.jpg) | ![Arrival day](docs/screens/tv-arrival.jpg) | ![During the stay](docs/screens/tv-during.jpg) |
| **Last day** | **Between guests** (nothing private on screen) | |
| ![Last day](docs/screens/tv-lastday.jpg) | ![Between guests](docs/screens/tv-between.jpg) | |

Shown with demo homes and demo guests around Byron Bay. They come with the code: open
`/tv/?home=lake`, `ridge`, `carriage` or `headland`, and add `&phase=arrival`, `lastday` or
`between` to see each moment.

## The Guest remote

The TV shows two codes: **1 · Join the Wi-Fi**, then **2 · Guest remote**. The remote opens in the
guest's phone browser, with nothing to install, and only works on your Wi-Fi. During a stay it
also shows the dates, the Wi-Fi, the door codes, the house rules and the check-out steps.

| The remote | Their room | House info |
|---|---|---|
| <img src="docs/screens/phone-remote.jpg" width="250" alt="The Guest remote"> | <img src="docs/screens/phone-room.jpg" width="250" alt="Aircon and lights for their room"> | <img src="docs/screens/phone-guide.jpg" width="250" alt="Wi-Fi, house info and local picks"> |
| **"Where's good for dinner tonight?"** | **"Book us a table at Pixie for 2"** (Open level) | |
| <img src="docs/screens/phone-dinner.jpg" width="250" alt="Dinner picks with Book a table buttons"> | <img src="docs/screens/phone-booking.jpg" width="250" alt="The booking card the guest confirms"> | |

- The **Ask** box: "put on that show about the lawyer who never went to uni", "chill music", "make
  my room cooler", "dim the lights", "will it rain tomorrow?", "where's good for dinner?"
- A D-pad, Back, Home, play and volume, the TV's streaming apps, and a card for each room they may
  control (aircon, lights), the pool and the speakers.
- Dinner answers come with a **Book a table** button for each place (its own booking page). At the
  Open level the agent can fill in the booking for them, after they check and tap **Book it**.

## Will it work on my TV?

The phone side (aircon, lights, the house guide, dinner picks and booking) runs on the phone and
the computer. It never touches the TV, so it works whatever TV you have. Only the TV screen and the
TV buttons depend on the brand. guest-tv now runs on every TV [couch-tv](https://github.com/Seagey/couch-tv)
does, the same way couch-tv does it there:

| Your TV | Welcome screen | TV buttons, apps and shows from the phone | Guest profile picker |
|---|---|---|---|
| **Google TV or Android TV** (TCL, Hisense Google TV, Sony, Philips Android, Kogan, Haier, Chromecast with Google TV, Google TV Streamer, Onn, Nvidia Shield) | Yes, as the TV's home screen: the Guest TV app ([the quick way](#the-quick-way)) or the couch-tv TV app ([by hand](#setup)) | Yes | Yes (Stan tested; Netflix by profile position) |
| **Fire TV on Fire OS** (Fire OS 6, 7 and 8: Stick 4K 1st gen and newer, Stick 4K Max, Cube) | Partial: the Guest TV app opens from the app row; set up by hand, the couch-tv TV app takes the Home key back, but Amazon's home flashes up first (Fire OS 6 needs a couch-tv release newer than 0.3) | Yes, over ADB | Not yet |
| **Fire TV on Vega OS** (Stick 4K Select and newer) | **New (Beta)**: guest-tv's own app, built once with Amazon's free tools, opened when the stick comes up ([how](docs/FIRE-VEGA.md)) | Arrows, OK and Back while guest-tv is in front, not volume or power; Netflix and YouTube open the show | No |
| **Samsung** (Tizen, 2016 and later) | Yes, as an app the computer opens each time the TV comes on ([how](#samsung)) | Yes. Netflix and YouTube open the show; other apps open on their home page | No |
| **LG** (webOS, and webOS TV Lite) | Yes, as an app the computer opens each time the TV comes on, through LG's Developer Mode ([how](#lg)) | Yes. Netflix and YouTube open the show; other apps open on their home page | No |
| **Roku** (TV or box) | **New (Beta)**: guest-tv's own Roku channel, opened each time the TV comes on, while Developer Mode is on ([how](docs/ROKU.md)) | Yes. Netflix and YouTube open the show; other apps open on their home page | No |
| **Hisense with VIDAA** | **New (Beta)**: a page that opens itself in the TV's browser, or a Guest TV tile on firmware that allows it ([how](docs/VIDAA.md)) | Yes: buttons, volume, mute, apps; a show opens its app, then the guest picks | No |
| **Philips with Titan OS** (mostly Europe) | Needs a Titan app: a Guest TV DevView app you make yourself, not there yet for most owners ([how](docs/PHILIPS-TITAN.md)) | **New (Beta)**: buttons, volume and the apps the TV lists | No |
| **Older Philips with Saphi** (about 2015 to 2019, not Android) | **New (Beta)**: a page that opens itself in the TV's browser, if your set offers one ([how](docs/PHILIPS-SAPHI.md)) | Yes: buttons, volume and the apps the TV lists | No |
| **Panasonic Viera** (My Home Screen and older Vieras) | **New (Beta)**: a page that opens itself in the TV's browser just after the TV comes on ([how](docs/PANASONIC.md)) | Yes: buttons, volume and mute, apps by name; a show opens its app | No |
| **VIZIO** (SmartCast, VIZIO OS) | No: VIZIO has no browser and takes no outside apps | **New (Beta)**: buttons, VIZIO's own Home, volume, mute, and Netflix, YouTube, Prime Video, Disney+ and others open on their own page ([how](docs/VIZIO.md)) | No |
| **Apple TV** | **New (Beta)**: Guest TV, guest-tv's own Apple TV app, opened when the Apple TV wakes. Installed free from a Mac with your own Apple ID and put back each week by the computer ([how](docs/APPLE-TV.md)) | Yes: buttons, play and pause, volume where the Apple TV controls the TV, opening apps; a show opens its app; no mute | No |
| **TiVo OS** | No known way yet | No known way yet | No |

**What is the same on every TV that is not Google TV or Android TV:** they all need the **computer at
home that stays on**, and on all of them **the maker's own Home button still opens the maker's own
home**: guest-tv opens itself on top, it does not replace that home. The Home key on the Guest remote
always brings guest-tv back. No Guest profile picker (these TVs give no way to read the screen), and
Spotify opens without searching. The New (Beta) paths are built from each maker's documentation and
couch-tv's work, and checked against a stand in TV on the computer so far. If you have one of them,
each page has a short read only first check, and an issue saying how it went helps everyone after you.

**Hisense, Sharp, Philips and other brands that sell more than one kind of TV:** it depends on the
model, not the brand. Their Google TV and Android TV models are the first row. Open **Settings,
System, About** (or **Device Preferences, About**): "Android TV OS" means the first row.

**Want everything on a TV that is not Google TV or Android TV?** Plug in a Google TV box (the Google
TV Streamer, a Chromecast with Google TV, an Onn) and set guest-tv up on that: you get the home
screen, the Guest profile picker and Spotify search, on any TV with an HDMI port.

Built and tested on a TCL and a Toshiba, both Android TV 11, in November 2026, and on a Samsung
Frame (2021) on 4 November 2026: install, pairing and the welcome screen with its menus. couch-tv's
LG version has run on nine real LGs, and guest-tv's LG app is built the same way. If you run guest-tv
on anything, please open an issue saying how it went.

## The quick way

For a **Google TV, Android TV or Fire TV (Fire OS)**: no AI, no ADB, no developer settings. About ten
minutes. Other TVs: do step 1, then [Samsung and LG](#samsung-and-lg) or [Every other TV](#every-other-tv).

**1. On the computer that stays on** (a Mac, a Linux box or a Raspberry Pi, on the same Wi-Fi as the TV):

```bash
git clone https://github.com/Seagey/guest-tv && cd guest-tv && sh scripts/start.sh
```

It sets up Python, asks the setup questions (your place, the Wi-Fi, the TV, what guests may control),
and keeps guest-tv running after a restart if you say yes. At the end it shows this computer's
address. Needs Python 3.10 or newer and [Claude Code](#what-you-need) signed in for the Ask box.

**2. On the TV:**

1. Install **Downloader** (the free one by AFTVnews) from the TV's app store (Google Play, or the
   Amazon Appstore on a Fire TV).
2. Open Downloader, type the code **`1061533`** with the TV remote, and press **Go**. It downloads
   the Guest TV app (`guest-tv.apk` from this repo's
   [latest release](https://github.com/Seagey/guest-tv/releases/latest)). If the code does not
   work, type **`couchtv.sites.underseage.studio/guest`** instead and press Go.
3. The first time, the TV asks to let Downloader install apps: press **Settings**, switch Downloader
   on, press Back. (Fire TV: **Settings, My Fire TV, Developer options, Install unknown apps**.) Then
   press **Install**, then **Open**.
4. **Guest TV** finds guest-tv on your Wi-Fi by itself in a few seconds and shows the welcome screen.
   If it does not, type the number step 1 showed and press **Connect**.
5. Optional: hold **Back** (or press **Menu** on a Fire TV remote) for Guest TV's settings, and press
   **Make Guest TV the home screen**. If Home still opens the TV's own home, switch on **Home button
   watch** there and in the TV's **Settings, Accessibility**. On a Fire TV, Amazon's Home button keeps
   Amazon's home: open Guest TV from the app row.

**3. On your phone:** scan the **Guest remote** code on the TV and ask for something.

The long way, every step by hand, is [Setup](#setup) below. It sets the TV up over ADB instead, with
couch-tv's TV app.

## Setting it up with an AI agent

Open this folder in Claude Code (or any coding agent) and say "set this up on my TV". It reads
[AGENTS.md](AGENTS.md), runs the checks, and walks you through the same questions `setup.py` asks:
your place, your TV, what guests may control, and how much the agent may do. It never signs in to
anything for you and never picks the Open level for you.

## What you need

- **A TV**: a Google TV or Android TV with Developer options and debugging on (step 1), or any TV in
  [Will it work on my TV?](#will-it-work-on-my-tv) ([Samsung and LG](#samsung-and-lg), and
  [Every other TV](#every-other-tv)). The phone side works with any TV.
- **A computer that stays on**, on the same Wi-Fi: a Mac, a Linux box or a Raspberry Pi. It runs the
  TV page, the remote and the agent, so it must never sleep. **Python 3.10 or newer**
  (`python3 --version`; tested on 3.11). Missing or older: on macOS `brew install python@3.11` or
  the installer from python.org; on Linux your distribution's package (for example
  `sudo apt install python3.11 python3.11-venv`).
- **Claude Code**, installed and signed in on that computer. The agent runs `claude -p` on your own
  Claude plan, with `ANTHROPIC_API_KEY` stripped first, so it never bills an API key.
- **One Wi-Fi.** The TV, the aircon, the lights, the computer and the guest's phone all on it.
- **A TV app** on a Google TV, Android TV or Fire TV: the Guest TV app (`guest-tv.apk`,
  [the quick way](#the-quick-way), no ADB), or for the by hand setup below the couch-tv TV app,
  `couch-tv-home.apk`, from the [couch-tv Releases page](https://github.com/Seagey/couch-tv/releases).
  Either shows guest-tv full screen and opens the TV's real apps from it.
- Optional: **AirTouch 5** aircon, smart lights through **Home Assistant** or **Philips Hue**,
  **Spotify** on the TV, and **Node.js 20+** and Google Chrome for agentic booking.

## Setup

### Step 1. Developer mode on the TV

Not a Google TV or Android TV: do steps 2 to 4, then follow [Samsung and LG](#samsung-and-lg) or
[Every other TV](#every-other-tv) instead of steps 1 and 5.

1. On the TV: **Settings, System, About**. Move to **Android TV OS build** (or **Build**) and press
   OK seven times, until it says you are a developer.
2. Back in **Settings, System**, open **Developer options** and switch on **USB debugging** (on some
   TVs it is called **Network debugging** or **ADB debugging**).
3. Find the TV's address: **Settings, Network and Internet**, your Wi-Fi, **IP address**. Use this
   number everywhere below, not a `.local` name.

The first time the computer connects, the TV asks "Allow USB debugging?". Tick **Always allow** and
press **OK**.

### Step 2. Get the code and set up Python

```bash
git clone https://github.com/Seagey/guest-tv && cd guest-tv
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

### Step 3. Answer the setup questions

```bash
.venv/bin/python setup.py
```

It checks the must-haves first (Claude Code signed in, the computer never sleeps, the packages, the
ADB key, the TV answers) and says how to fix anything missing. Then it asks: a guest room or a
stay, the host's name, the guest Wi-Fi, the Airbnb calendar link (stays only), the TV's brand and address,
which rooms guests may control for the aircon and the lights, which streaming apps are signed in,
and the agent level. Run it again any time to change an answer; `setup.py --check` only checks.

### Step 4. Run it, and keep it running

```bash
.venv/bin/python server.py
```

To start it on boot and restart it if it stops: `service/guest-tv.plist` (Mac) or
`service/guest-tv.service` (Linux). Each file says how to install it.

### Step 5. Put it on the TV

```bash
TV_IP=<tv address> .venv/bin/python tools/tv_app.py install couch-tv-home.apk
TV_IP=<tv address> .venv/bin/python tools/tv_app.py home --home guest
```

`install` puts the couch-tv TV app on the TV. `home` writes down the TV's current home screen, then
makes the app the home and opens guest-tv in it, so the Home button always comes back to the welcome
screen. On a Fire TV, `home` also switches on the app's Home button watch, which puts guest-tv back
whenever Amazon's home opens. Some other TVs (Haier, some TCL and Xiaomi) also open their own home
after Home or a restart: if yours does, say yes to the optional **Home button watch** question in
`setup.py` (or add `--watch` to `home`), and the same watch puts guest-tv back (couch-tv#98). It is
off unless you choose it. On a **TCL** with the watch chosen, `home` also lets the app start at boot,
and asks you to switch **Home button watch** on once from the TV's own **Settings, Accessibility**
with the remote: that is what keeps guest-tv as the home after a restart (couch-tv#94). Use `open` instead of `home` to show it without changing the home. Use your home's id
(`guest`, or the one you gave a stay in step 3). If the computer has more than one address, add
`--url http://<this computer's address>:5410`. `status` shows what is on the TV now.

### Step 6. Try it

Scan the **Guest remote** code on the TV with your phone and ask for something. Then test the guard
rails yourself: `.venv/bin/python tools/agent_test.py` (73 asks, about 6 minutes; every one must
pass) and the code checks with no AI: `.venv/bin/python tools/devices_test.py`.

## Undo

```bash
TV_IP=<tv address> .venv/bin/python tools/tv_app.py undo            # the old home screen is back
TV_IP=<tv address> .venv/bin/python tools/tv_app.py undo --remove   # and the TV app is removed
```

Then stop the service if you installed one (Mac: `launchctl bootout gui/$(id -u)/guest-tv`; Linux:
`sudo systemctl disable --now guest-tv`). Nothing on the TV was switched off or deleted, so there is
nothing else to put back. With only the TV remote: in **Settings, Apps**, find the default **Home**
app setting (the menu name varies by TV) and pick the old home.

## Samsung and LG

Samsung and LG let no app replace their home screen. So on these TVs guest-tv is **an app the
computer opens each time the TV comes on**, the way couch-tv works there:

- **The guest-tv app** (`tv-apps/`): one small page that shows the welcome screen from the computer,
  full screen. If the computer is off it says "Waiting for the house computer" and keeps trying.
- **The hook**: `server.py` checks the TV every 2 seconds. When the TV comes on and nothing else is
  on screen (live TV, an input, the TV's menu), it opens guest-tv within a few seconds. It leaves
  the TV alone when an app is on screen, and for 20 seconds after a guest's own command.
- **The Guest remote and the agent** reach the TV over its own network remote, from `tvbrands.py`:
  keys, volume, mute, opening apps. Netflix and YouTube open the show. Other apps open on their home
  page and the agent says to pick the show there.

Set the brand in `setup.py` (or `"tv_kind": "samsung"` or `"lg"` in `data/settings.json`), then:

### Samsung

1. **Developer Mode on the TV.** Open **Apps**, press **1 2 3 4 5** on the remote, switch
   **Developer mode** on and type this computer's IP address. Restart the TV by holding the power
   button until it switches off and on again.
2. **Get Apps2Samsung** (free, open source) and its command line, `apps2samsung-cli`. It installs
   the app and signs it with **your own** Samsung account. The first install opens a browser for the
   Samsung sign-in; guest-tv never sees it.
3. **Install, pair, open:**

```bash
TV_KIND=samsung TV_IP=<tv address> .venv/bin/python tools/tv_app.py install
TV_KIND=samsung TV_IP=<tv address> .venv/bin/python tools/tv_app.py pair
TV_KIND=samsung TV_IP=<tv address> .venv/bin/python tools/tv_app.py open
```

`install` builds the app with this computer's address in it and installs it. `pair` makes the TV ask
"Allow guest-tv to connect?": press **Allow** on the TV (once; the token stays in `data/`). Then
switch the TV off and on: guest-tv comes up by itself.

On a Frame, Art Mode counts as on, so guest-tv opens when the Frame wakes from standby, not when it
leaves Art Mode.

### LG

1. **Developer Mode on the TV.** Install LG's **Developer Mode** app from the LG Content Store, sign
   in with a free LG developer account, switch **Dev Mode Status** on (the TV restarts), then switch
   **Key Server** on and note the passphrase.
2. **LG's tools on this computer:**

```bash
npm install -g @webos-tools/cli
ares-setup-device -a tv -i "username=prisoner" -i "host=<tv address>" -i "port=9922"
ares-novacom --device tv --getkey
```

3. **Install, pair, open:** the same three commands as Samsung with `TV_KIND=lg`. For `pair`, press
   **Accept** on the TV.

LG removes Developer Mode apps when the Developer Mode session runs out. So once a day, as the TV
comes on, the computer presses Developer Mode's **Extend** for you (with `ares-launch` when LG's
tools are installed), tries again an hour later if that failed, and waits for Developer Mode's own
screen to come and go before putting guest-tv back on top. The computer also remembers which of the
TV's two remote ports answered (webOS 10.3.2 drops the plain one after a restart). It is built the
same way as couch-tv's LG version, which has run on nine real LGs (webOS 4.10 to webOS 26) and on a
webOS TV Lite set (couch-tv#112), and tested here against a stand-in. guest-tv's own first real LG
report is still wanted: please open an issue.

### Undo on Samsung or LG

```bash
TV_KIND=samsung TV_IP=<tv address> .venv/bin/python tools/tv_app.py undo --remove
```

That removes the guest-tv app. Add `"tv_hook": false` to `data/settings.json` (or stop
`server.py`) and the computer stops opening it. Nothing else on the TV was changed.

## Every other TV

Roku, Hisense VIDAA, Philips (Titan OS and Saphi), Panasonic, VIZIO, Apple TV and Fire TV on Vega OS
work the way Samsung and LG do: the computer opens guest-tv each time the TV comes on (as a channel,
an app or a page in the TV's own browser), and the Guest remote reaches the TV over its own network
remote. Each has its own page with the steps and the honest limits:

| TV | `TV_KIND` | What goes on the TV | Pairing | Steps |
|---|---|---|---|---|
| Roku | `roku` | guest-tv's Roku channel (sideloaded, Developer Mode) | none | [docs/ROKU.md](docs/ROKU.md) |
| Hisense VIDAA | `vidaa` | nothing: a page in the TV's browser (or a tile) | a PIN on the TV | [docs/VIDAA.md](docs/VIDAA.md) |
| Philips Titan OS | `titan` | a Guest TV app in Titan's DevView, when you have one | a PIN on the TV | [docs/PHILIPS-TITAN.md](docs/PHILIPS-TITAN.md) |
| Older Philips (Saphi) | `saphi` | nothing: a page in the TV's browser | none, or a PIN | [docs/PHILIPS-SAPHI.md](docs/PHILIPS-SAPHI.md) |
| Panasonic Viera | `panasonic` | nothing: a page in the TV's browser | a PIN on 2018 and newer | [docs/PANASONIC.md](docs/PANASONIC.md) |
| VIZIO | `vizio` | nothing (Guest remote only) | a PIN on the TV | [docs/VIZIO.md](docs/VIZIO.md) |
| Apple TV | `appletv` | Guest TV, guest-tv's Apple TV app (needs a Mac) | a PIN on the Apple TV | [docs/APPLE-TV.md](docs/APPLE-TV.md) |
| Fire TV on Vega OS | `vega` | guest-tv's Vega app (built once with Amazon's tools) | none | [docs/FIRE-VEGA.md](docs/FIRE-VEGA.md) |

Set the kind in `setup.py` (or `"tv_kind"` in `data/settings.json`), then the same commands as Samsung
and LG, with that kind:

```bash
TV_KIND=roku TV_IP=<tv address> .venv/bin/python tools/tv_app.py status    # reads only
TV_KIND=roku TV_IP=<tv address> .venv/bin/python tools/tv_app.py install   # where something goes on the TV
TV_KIND=roku TV_IP=<tv address> .venv/bin/python tools/tv_app.py pair      # press Allow, or type the PIN the TV shows
TV_KIND=roku TV_IP=<tv address> .venv/bin/python tools/tv_app.py open
```

Roku and Apple TV draw the welcome screen themselves (they have no web pages), from
`/api/tv/native`: the photo, the greeting, the Wi-Fi and Guest remote codes, the weather, and door
codes only during a stay. The house guide menus are on the Guest remote there.

## What guests can control

`setup.py` asks this, or set it yourself. The TV is always included.

| Device | How | Set in |
|---|---|---|
| Aircon | AirTouch 5 on your Wi-Fi | `settings.json` `"aircon"` |
| Lights | Home Assistant (covers Hue, LIFX, TP-Link, Govee, Nanoleaf and most others) or Philips Hue direct | home `"lights"` |
| Pool | Home Assistant: a temperature sensor, and a heater switch or heat pump | home `"pool"` |
| Speakers | Home Assistant (covers Sonos, Google and Nest, Bose, HEOS and most others) | home `"speakers"` |
| Anything else | your own buttons, agent level Plus (below) | `data/actions.json` |

Which rooms, per device, in the home as `"control"`:

```json
"control": { "aircon": "their room", "lights": "all" }
```

`"their room"` (the room in the home's `"room"`, best for a guest room), `"all"` (the guest has the
whole place), a list such as `["Living", "Deck"]`, or `"none"`. Lights look like this:

```json
"lights": { "kind": "home_assistant", "url": "http://homeassistant.local:8123",
            "rooms": { "Bed 3": ["light.bed_3_lamp"], "Living": ["light.lounge", "light.dining"] } }
```

The Home Assistant token (`ha_token`) or Hue key (`hue_user`) goes in `data/private.json`. A room with
lights gets a Lights card on the remote (on, off, brightness), and the agent can dim or switch them.
Rooms with no smart lights show nothing.

### Smart home: pool and speakers

With a pool or speakers set up, the TV's Climate tile becomes a **Smart home** tile (inside
temperature, pool water, what is playing), and OK on it opens one screen for the aircon, pool,
speakers and lights, all driven with the TV's own remote.

```json
"pool": { "kind": "home_assistant", "url": "http://homeassistant.local:8123",
          "temp": "sensor.pool_temperature", "heater": "switch.pool_heater" },
"speakers": { "kind": "home_assistant", "url": "http://homeassistant.local:8123",
              "rooms": { "Living": "media_player.living", "Deck": "media_player.deck" } },
"control": { "aircon": "all", "lights": "all", "speakers": "all", "pool": "all" }
```

- **Pool:** guests always see the water temperature. They can switch the heater only with
  `"pool": "all"` in `"control"`. A `climate.*` heat pump works as the heater too.
- **Speakers:** play, pause, next and volume, in the rooms `"control"` allows. What plays is up to
  the guest (AirPlay or Spotify Connect from their phone).
- The agent can do the same: "heat the pool", "music on the deck", "turn it down a bit".
- Headland House (`/tv/?home=headland`) shows all of it with pretend devices (`"kind": "demo"`).

## Your own photo

The demo homes come with their own photos. To show your place instead:

```
.venv/bin/python tools/home_photo.py <home-id> my-house.jpg            # the main photo
.venv/bin/python tools/home_photo.py <home-id> lounge.jpg --inside     # beside the house guide
.venv/bin/python tools/home_photo.py <home-id> beach.jpg --area        # on "Around here"
```

A wide (landscape) photo looks best. It is cut to 16:9 and gets a frosted copy for the glass clock.
The clock sits on top of your photo (the demo homes also have a cut-out that tucks it behind the
scenery).

## Agent levels: how much the agent may do

Whatever the agent can do, a guest can try to talk it into. So you choose. In `settings.json`:
`"agent": {"level": "locked"}` (the default).

| Level | What it can do | The risk |
|---|---|---|
| **Locked** (default) | The TV, music, the devices and rooms you picked, the weather and your area. Dinner answers get a **Book a table** button that opens the restaurant's own booking page. The guest books it themselves. | None outside that list. The AI has no tools at all. It picks from a short menu and the code checks every pick. |
| **Plus** | Locked, plus your own buttons in `data/actions.json` (start from `actions.example.json`): a webhook (n8n, Zapier, Home Assistant) or a Home Assistant script. Each has typed settings the code checks, and `"confirm": true` makes the guest tap Confirm first. | Only what your buttons do. Only add what you'd let any guest press. |
| **Open** | Plus, and the AI gets web search and any tools you plug in (MCP servers). It can **book a table for the guest**: it fills in the restaurant's booking page in a browser. | A clever guest can get it to do anything those tools can do. It also uses more of your Claude plan, and asks take longer (about 20 to 40 s). |

Never at any level: shell commands, your files, your computer, other devices on your Wi-Fi.

### Agentic booking (Open level)

`setup.py` turns this on for you. By hand:

1. Install Node.js (for `npx`). Google Chrome on the computer, or run `npx playwright install chromium` once.
2. `data/booking-mcp.json`:
   ```json
   { "mcpServers": { "browser": { "command": "npx",
       "args": ["-y", "@playwright/mcp@0.0.84", "--headless", "--isolated", "--browser", "chrome"] } } }
   ```
3. `settings.json`:
   ```json
   "agent": { "level": "open", "open": { "web": true },
              "booking": { "mcp_file": "booking-mcp.json", "allowed_tools": ["mcp__browser"] } }
   ```
4. Give each restaurant in your house guide its booking page as `"book"` (`guide_writer.py` finds these).

How it goes: the guest asks "book us a table at Pixie for 2 at 7 on Saturday". The remote shows a card
with the place, people, time and name. The guest checks it and taps **Book it**. Only then does the
agent open the restaurant's booking page and fill it in. It works with whatever the restaurant uses
(its own form, SevenRooms, OpenTable, Resy, Tock and others), in any country.

What it will never do: pay, type a card number, make an account, sign in, or tick a newsletter box.
If a booking needs any of those, or the time is taken, it stops and tells the guest (with nearby
free times), and the guest gets the booking page instead. It only books places in your guide.

Prefer a booking service's own tool? If one in your area has an MCP server, list it in
`booking-mcp.json` instead and put its tool names in `allowed_tools`.

Test it without bothering a real restaurant: `.venv/bin/python tools/booking_agent_test.py` (a
pretend restaurant on your computer: a normal booking, a card deposit, and a full time slot).

## More about the Guest remote

- Stay homes get a new link for each booking, and it stops at check-out. The guest room's link lasts
  until you reset it: `POST /api/remote/reset?home=guest&key=<host_key>`.
- 20 asks an hour per guest, one at a time.
- Music is Spotify on the TV, signed in to your account. A music ask takes about 45 seconds, because
  Spotify's TV app has to be stepped through by its Search page.
- List the apps you are signed in to as `"guest_apps"` in `data/settings.json` (for example
  `["stan", "netflix", "youtube"]`). Others are hidden, so a guest never lands on a login screen.

## Airbnb bookings

Put your listing's calendar link (Airbnb: Calendar, Availability, Connect calendars, Export) in the
home as `calendar_url` (`setup.py` asks for it). The TV then knows each booking's dates and shows
check-in and check-out.

Airbnb leaves the guest's name out of that link. To get it, guest-tv reads Airbnb's booking emails:

- **Easiest:** forward or save each "Reservation confirmed" email as a `.eml` file into
  `data/bookings-inbox/`.
- **Hands-free:** let it read your mailbox (read only). In `data/settings.json`:
  `"bookings": {"imap": {"host": "imap.gmail.com", "user": "you@example.com"}}`, and put an
  app password (not your normal password) in `data/private.json` as `"bookings_password"`.

It takes the guest's first name and how many are coming, and a cancel email takes them off again.
A name you type in the host panel always wins. Check what it found:
`/api/bookings?key=<host_key>&now=1`. Test it with no Airbnb account: `.venv/bin/python tools/booking_test.py`.

## Host panel

`/p/?home=guest&key=<host_key from data/private.json>` adds a box to set the guest's name and dates.

## Your house guide, written by AI

```bash
.venv/bin/python guide_writer.py --area "Bangalow, NSW" --home "a railway carriage cabin for 2" \
  --notes my-notes.md --out data/homes/carriage/guide.json
```

Set `--area` to where your home is. Paste whatever you have into the notes file (or nothing).
Claude leads with places to eat and things to do, checks every local place on the web (and its
booking page), and never invents a phone number. Read it and edit it before guests see it.

## Guest profiles in streaming apps

When a guest opens Netflix, Stan, Prime Video or Disney+, the TV picks the **Guest** profile for them,
so they never land in yours and your watch history stays yours.

**You do this once, in each app** (the TV cannot make profiles or sign in for you):

1. Sign in to each streaming app on the guest TV yourself.
2. In each app, add a profile called **Guest**. If the app is full (Stan and Netflix allow 5), rename
   one you do not use.
3. Tell your agent it is done. It checks each app with `tools/tvui.py` and says which ones work.

The setting lives in `data/settings.json` under `profiles`:

```json
"profiles": {
  "on": true,
  "tv": "<the TV's IP address>",
  "names": ["Guest", "Guests", "Visitor", "Visitors"],
  "blind": { "com.netflix.ninja": { "position": 3 } }
}
```

- `tv`: the TV's address. Use the number, not a `.local` name (two devices can share one).
- `names`: what a guest profile may be called. Add your own word if you use another one.
- `blind`: for apps that hide their screen from the computer (Netflix does), the guest profile's
  place in the row (1 = first). Used only when the app has just started and nothing is playing.

What it did shows at `/api/profiles` and in `logs/profiles.log`.

## Film mode

Filming a video of your setup? Set `"film": true` in `data/settings.json`. Each home's `film.json`
(if it has one) then replaces the host's name, the Wi-Fi and anything else you list, so nothing
private shows on camera. Set it back to `false` when you're done.

## How it fits together

```
guest's phone (/r/ Guest remote, /p/ house info)
        |
        v
this computer: server.py ----> the TV (Google TV over ADB; every other TV over its own network remote)
        |        |      \----> aircon (AirTouch 5) and lights (Home Assistant, Hue)
        |        v
        |   guest_agent.py: claude -p, no tools (Locked); the code checks every pick
        v
the TV: the couch-tv TV app (Google TV) or guest-tv's own app or the TV's browser shows /tv/
        (Roku and Apple TV draw it from /api/tv/native)
```

| Path | What it is |
|---|---|
| `server.py` | the pages and the API behind them |
| `guest_agent.py` | the agent behind the Ask box, and the code that checks what it picks |
| `tvctl.py` | TV control over ADB, from fixed tables of keys and apps |
| `tvbrands.py` | the same for Samsung and LG, the list of every other TV, and the hook that opens guest-tv when the TV comes on |
| `tv_roku.py`, `tv_vidaa.py`, `tv_philips.py`, `tv_panasonic.py`, `tv_vizio.py`, `tv_appletv.py`, `tv_vega.py` | one self contained driver per TV, built on `tvbrands.py` |
| `tv-apps/` | guest-tv's own TV apps: Guest TV for Android TV and Fire TV (`android/`, built by its `build.sh`), Samsung, LG, Roku, Apple TV (`tvos/`), Fire TV Vega, and the Titan start page (`tools/tv_app.py build <kind>` packs them) |
| `docs/` | setup and limits for each TV that is not Google TV, Samsung or LG |
| `devices.py` | smart lights (Home Assistant, Hue) and your own actions |
| `profiles.py` | picks the Guest profile when a streaming app asks "Who's watching?" |
| `bookings.py` | reads Airbnb booking emails for the guest's name and how many are coming |
| `setup.py` | the setup questions (and `--check` for the must-haves) |
| `guide_writer.py` | writes `guide.json` with Claude from your notes and the area |
| `data/homes/<id>/` | each home: `home.json` (name, photos, rooms, dates) and `guide.json` (welcome, rules, how-to, local picks, check-out) |
| `data/settings.json` | port, weather place, aircon, TV, apps, agent level |
| `data/private.json` | your Wi-Fi, codes, guest names, tokens, host key. Made on first run, never in git |
| `data/actions.example.json` | example buttons for agent level Plus |
| `tools/` | `tv_app.py` (put it on the TV), `tvui.py` (step through the TV by hand), the tests (`brands_test.py`, `security_test.py` and one `<kind>_test.py` per TV, all against stand-ins) |
| `scripts/` | `start.sh` (the quick way, on the computer) and `privacy-scan.sh` |
| `service/` | keep it running on a Mac (launchd) or Linux (systemd) |
| `web/` | the TV page, the phone pages, fonts and the demo photos |

## Privacy and safety

- Your Wi-Fi, door codes, guest names and tokens are in `data/private.json`. Your own buttons and
  booking setup are in `data/actions.json` and `data/booking-mcp.json`. All three are ignored by git.
- Before you push a fork, run `scripts/privacy-scan.sh`. It checks for private addresses, emails,
  phone numbers, MAC addresses, home network names and secrets, in the files and the git history.
  Give it a file of your own words to block: `scripts/privacy-scan.sh my-denylist.txt` (one word per
  line, keep that file out of the repo). A `my-denylist.txt.allow` file next to it lists exact text a
  line may carry on purpose (your own public website, say).
- The Guest remote only answers with the code from the TV, and a stay's code stops at check-out.
  Anyone on your Wi-Fi who scans the TV can use it, so put guests on a guest network if you can.
  Do not forward a port to this computer.
- The computer takes JSON only on every POST (a form on some other website cannot reach it), answers
  only to its own names in the Host header (an IP address, `.local`, localhost, your `public_url`,
  or names you list in `"hosts"` in `data/settings.json`), and after five different wrong codes or
  host keys from one address in a minute it answers 429 for the rest of that minute. App names are
  checked before anything reaches an Android TV's shell, and no key is ever in a TV page's address.
  These came over from couch-tv (#72, #73, #110).
- `tools/tvui.py` drives a real TV, so it refuses to run unless `GUEST_TV_REAL_TV=1` is set. The
  tests in `tools/` only ever talk to stand-ins on this computer.
- The door code only shows on the TV during a stay. Between stays nothing private is on screen.
- Agent levels: see above. Locked is the default, and the guard rail tests are in the repo.

## Limits

- Every TV that is not Google TV or Android TV: guest-tv opens itself on top, it is not the home
  screen, so the TV's own Home button still opens the TV's menu. No Guest profile picker there, and
  Spotify only opens. They need the computer to stay on.
- VIZIO is the Guest remote only: its welcome screen cannot open on the TV. Philips Titan OS needs a
  Titan app for the welcome screen. Roku and LG lose guest-tv if Developer Mode is switched off, and
  Apple TV's free signing lasts a week (the computer redoes it).
- The New (Beta) TVs (Roku, VIDAA, Philips, Panasonic, VIZIO, Apple TV, Fire TV on Vega OS) are checked
  against stand ins so far. First reports from real TVs are wanted.
- Some Google TV models keep Google's own home on the Home button even after `tools/tv_app.py home`.
  couch-tv's `apply.sh` can switch Google's home off if you need that.
- Aircon is AirTouch 5 only so far. Other aircon can be added as your own action (Plus level) through
  Home Assistant.
- Lights were tested against Home Assistant and Hue stand-ins, not real bulbs. Please open an issue
  if yours behave differently.
- The agent's knowledge of shows stops at its training date. Very new shows work by name, not always
  by description.
- Spotify music asks take about 45 seconds.
- No support promise. It works on the TVs it was built on. Your TV may differ.

## Credits

- The demo home photos (`web/homes/`) were generated for this project and are free to use.
- Fonts: Inter and Antonio (both SIL Open Font Licence).
- Where shows stream: JustWatch's public search (credit them if you publish anything built on this).
- Weather: Open-Meteo.
- The TV app and the glass look: [couch-tv](https://github.com/Seagey/couch-tv).

## Shout me a coffee

guest-tv is free. If it made your day a bit easier and you'd like to say thanks, you can [shout me a coffee](https://buy.stripe.com/3cIdR8deM30bexRaYl6Vq0s), any amount you like.

MIT licence, see `LICENSE`.
