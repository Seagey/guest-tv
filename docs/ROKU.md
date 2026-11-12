# guest-tv on a Roku

**New (Beta).** Checked against a stand in Roku on the computer so far, first reports from real TVs
wanted. It is built from Roku's own documentation and from couch-tv's Roku driver, which was built the
same way.

Roku lets no app replace its home screen, and a Roku channel cannot be a web page. So guest-tv on a
Roku (a Roku TV, or a Roku stick or box) is two parts:

- **guest-tv's own Roku channel** (`tv-apps/roku`). It draws the welcome screen itself, from the same
  data the TV page uses: the home's photo full screen with a soft shade, the clock and the date with the
  weather, the welcome and the line under it, a **1 · Join the Wi-Fi** card (QR code, network and
  password), a **2 · Guest remote** card (QR code), the weather, and the door codes only while the
  computer shows them. Under that, the apps the guest may open. It asks the computer again every minute.
  While the computer does not answer it shows "Welcome, Waiting for the house computer".
- **The computer** (`server.py`, with `tv_roku.py`) talks to the Roku over Roku's External Control
  Protocol (plain HTTP on port 8060, no pairing). Each time the TV is switched on and nothing else is on
  screen, it opens guest-tv's channel. The Guest remote and the guest agent press keys and open apps the
  same way.

It needs the computer at home that stays on. Without it the channel shows only the waiting message.

## What works

| | Roku |
|---|---|
| Welcome screen | Yes, as guest-tv's own channel, opened by the computer each time the TV comes on |
| Wi-Fi and Guest remote QR codes, weather, door codes | Yes, drawn by the channel (door codes only while the computer shows them) |
| Apps on the welcome screen | Yes: left, right and OK; they open through the computer |
| Guest remote: arrows, OK, Back, play and pause, skip | Yes, when "Control by mobile apps" allows it (setup step 2) |
| Guest remote: volume up, down and mute | On a Roku TV. A Roku stick or box has no volume of its own. Mute is a toggle: a Roku reports no mute state |
| Guest remote: Home | Opens guest-tv's channel |
| Opening apps from the phone | Yes, the guest apps the Roku has |
| Shows from the phone | Netflix opens the title and YouTube the video with Roku's deep link (not yet seen on a real Roku). Other apps open on their own page |
| Spotify | Just opens. No search |
| Guest profile picker | No. A Roku gives no way to read the screen |
| Screenshots, a volume level, what is playing | No |

## Honest limits

- **Roku's own Home button still opens Roku's home.** guest-tv is a channel that opens itself, not a
  home screen. The computer opens it again the next time the TV comes on, and Home on the Guest remote
  opens it straight away.
- **The channel lives while Developer Mode is on.** A sideloaded channel goes when Developer Mode is
  switched off. Whether a factory reset, a Roku update or a long power cut removes it was not checked.
- **One sideloaded channel at a time.** A Roku holds one, always called `dev`. Installing guest-tv
  replaces any other one, for example couch-tv's Roku channel, and installing another one later replaces
  guest-tv's.
- **No Guest profile picker.** A Roku cannot say what is on screen inside an app.
- **Spotify just opens**, and the guest picks.
- **No screenshots.**
- **A Roku stick or box** may stay on when the TV is switched off, and then the computer cannot see the
  TV come on. Home on the Guest remote still opens guest-tv. Not checked on a real Roku.
- The house guide, dinner picks and the host's welcome note stay on the phone. The Roku screen keeps to
  the welcome, Wi-Fi, Guest remote, weather, codes and apps.
- Developer Mode can be used by anyone on the home network who knows the developer password, so make it
  one that is not used anywhere else.

## Set it up (the owner, or their AI agent)

### 1. Developer Mode on the Roku

On the Roku remote, with the Roku home on screen, press

**Home three times, Up twice, Right, Left, Right, Left, Right**

The Developer Settings screen opens. Choose **Enable installer and restart**, accept the licence and make
a **developer password** (the user name is always `rokudev`). No Roku account is needed. The Roku
restarts. guest-tv never stores this password.

### 2. Control by mobile apps

Newer Roku OS limits remote control from the network. On the Roku open

**Settings, System, Advanced system settings, Control by mobile apps, Network access**

and choose **Permissive** (older Roku OS) or **Enabled** (newer). The names differ between Roku OS
versions. If the Guest remote later says "the Roku is refusing remote control", this is the step to
check.

### 3. Tell guest-tv about the TV

Give the Roku a fixed address in the router (DHCP reservation). Its address is in Settings, Network,
About. Then set `"tv_kind": "roku"` and the TV's address for the home (or in `data/settings.json`).

### 4. Put the channel on the Roku and open it

```sh
TV_KIND=roku TV_IP=<tv address> .venv/bin/python tools/tv_app.py status
TV_KIND=roku TV_IP=<tv address> .venv/bin/python tools/tv_app.py install
TV_KIND=roku TV_IP=<tv address> .venv/bin/python tools/tv_app.py open
```

`install` builds `build/guest-tv-roku.zip` with this computer's address and the home baked in, then
signs in to the Roku's developer installer as `rokudev` and uploads it. It asks for the developer password,
or reads `ROKU_DEV_PASSWORD` from the environment, and never keeps it. Add `--url http://192.0.2.20:5410`
if the guess of this computer's address is wrong (use the number address: a Roku may not find a `.local`
name), and `--home <id>` for a home other than the default. There is no `pair` step: a Roku needs none.

By hand instead: open `http://<tv address>` in a browser on the same network, sign in as `rokudev`,
upload `build/guest-tv-roku.zip` and press **Install** (or **Replace**).

`server.py` then opens guest-tv each time the TV comes on (`"tv_hook": false` turns that off).

### Undo

```sh
TV_KIND=roku TV_IP=<tv address> .venv/bin/python tools/tv_app.py undo --remove
```

removes guest-tv's channel (it asks for the developer password). Or on the Roku: highlight **Guest TV** on
the home row, press `*` and choose **Remove channel**. Then switch Developer Mode off with the same key
sequence (**Disable installer and restart**), and put Control by mobile apps back if you changed it.
Nothing else on the Roku is changed, and nothing about the Roku is kept on the computer.

## First check (read only)

From the computer, with the TV on:

```sh
curl http://<tv address>:8060/query/device-info
curl http://<tv address>:8060/query/apps
TV_KIND=roku TV_IP=<tv address> .venv/bin/python tools/tv_app.py status
```

The first two only read and should answer with XML (`power-mode` says `PowerOn` while the TV is on). Please
send what `power-mode` says while the TV is on and while it is off: Roku documents only `PowerOn`, so
guest-tv treats any other word as off.

Then, in this order: does `install` say "Installed", does the channel show the welcome with the photo and
both QR codes, does an arrow from the Guest remote move on the TV, does switching the TV off and on open
guest-tv, and do Netflix and YouTube open a show from the phone. Please open an issue with what happened,
the Roku model and the Roku OS version, even if everything worked.

## How it works

- The hook checks `query/device-info` every 2 seconds. When the TV goes from off (standby or gone from the
  network) to on, it reads `query/active-app`. Roku's home, a screensaver, live TV or an input count as
  nothing, and then it sends `launch/dev?home=<id>`. If an app is in front, or a guest command ran in the
  last 20 seconds, it leaves the TV alone. If the app in front cannot be read, it also leaves the TV alone.
- Apps come from `query/apps`, every 30 minutes: Netflix (12), YouTube (837) and Prime Video (13) by their
  Roku ids, the rest by the name the Roku lists them under. An id is only used when the Roku itself lists
  it, and any id that is not plain letters, numbers, dots and dashes is ignored. The Australian apps have
  no known Roku id, and some are missing from some Australian Roku stores.
- Netflix opens a title with `launch/12?contentId=<title id>&mediaType=series`, YouTube with
  `launch/837?contentId=<video id>&mediaType=live`. Each channel decides what it does with these, so they
  may only open the app on a real Roku.
- A Roku that answers 403 is being limited by Control by mobile apps: guest-tv says so in plain words
  instead of looking like a dead TV.
- The channel shows the house's time: the computer sends its own time, and the channel keeps the
  difference from the Roku's clock, so a Roku set to another time zone still shows the right time.
- Only fixed tables reach the TV: the key names, the guest apps' ids from the Roku's own list, guest-tv's
  channel, and a Netflix or YouTube id taken from a link. Nothing a guest types reaches the Roku.

## Testing

`tools/roku_test.py` runs a stand in Roku and a stand in developer installer on the computer and checks
the driver, the hook, the build and the install (no real TV, no network). The channel's BrightScript was
checked with BrighterScript and `@rokucommunity/bslint` (couch-tv's rules) with no errors and no warnings,
and run once in the brs-engine simulator against a pretend computer. A simulator is not a Roku.

Sources: Roku's [External Control API](https://developer.roku.com/docs/developer-program/dev-tools/external-control-api.md),
[deep linking](https://developer.roku.com/docs/developer-program/discovery/implementing-deep-linking.md),
[developer setup](https://developer.roku.com/docs/developer-program/getting-started/developer-setup.md), and
couch-tv's `docs/ROKU.md`.
