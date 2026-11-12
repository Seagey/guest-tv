# guest-tv on a Hisense VIDAA TV

**New (Beta).** Checked against a stand in TV on the computer so far, first reports from real VIDAA TVs
wanted. Hisense publishes nothing about how its TVs talk to a phone remote, so parts of `tv_vidaa.py` are
our best reading of it, not confirmed facts. Expect the first owner to find something that needs fixing.

## What guest-tv does on this TV

VIDAA (Hisense's own system, being renamed V or V Home OS on 2026 models) does not run Android apps and
does not let anything replace its home screen. So guest-tv's welcome screen on VIDAA is **a page that opens
itself, not a true home screen**:

- **The hook.** The computer running guest-tv watches the TV the way Hisense's own phone app does. Each
  time the TV is switched on and lands on its own home or live TV, guest-tv's welcome page opens within a
  few seconds.
- **The page** opens in the TV's own web browser, or, on firmware that still allows it, as a **Guest TV
  tile** on the TV's app row.
- **The Guest remote on the guest's phone** (arrows, OK, Back, volume, mute, open an app) and the guest
  agent work through the same connection.

It needs the computer that stays on. Without one there is nothing on the TV to open the page.

## What works and what does not

| | VIDAA |
|---|---|
| Welcome screen on the TV | In the TV's browser or a tile. Not yet seen on a real TV |
| Opens by itself when the TV is switched on | Yes, with guest-tv running (not yet seen on a real TV) |
| The remote's Home button | **Still opens VIDAA's home.** That cannot change without rooting the TV, and guest-tv never roots a TV. The Home key on the Guest remote opens the welcome page again |
| Guest remote: arrows, OK, Back, play and pause, volume up and down, mute | Built. The key names are unconfirmed |
| Open Netflix, Stan, YouTube and the other guest apps | Yes, from the TV's own app list |
| Play a named show | The app opens on its own page and the guest picks the show there. No deep link into a show is known on VIDAA |
| Spotify | Opens, the guest picks. No search |
| Which app is in front | Not really. VIDAA says where it is (home, live TV, an input, a menu, standby). guest-tv adds the last app it opened itself |
| Volume level, typing, screenshots | No |
| Guest profile picker | No |
| Root | **Never** |

## Which VIDAA versions should work

Expected from what owners of these TVs report about the TV's phone remote, not from our own tests:

- **Older and mid VIDAA** (VIDAA U6 and U7, many 2023 and early 2024 builds): the Guest remote and the
  hook, and probably the tile.
- **Newer VIDAA** (2024 on): the remote and the hook through the TV's browser, **no tile** (the firmware
  refuses it). It needs the client certificate in step 2.
- **Some sets** answer on the network but ignore the control messages. Then nothing here works and the
  first check says so.

A firmware update can change any of this overnight.

## Set it up

You or your AI agent do these once. Use `TV_KIND=vidaa TV_IP=<tv address>` before each command, and set
`"tv_kind": "vidaa"` in `data/settings.json` so guest-tv knows which TV it has.

### 1. On the TV

- Note the TV's address (Settings, Network). A fixed address (a reservation in your router) saves
  trouble later.
- Switch on **Wake on LAN** if the TV has it (Ethernet is more reliable than Wi-Fi for this). guest-tv
  does not turn the TV on itself, but the setting does no harm.

### 2. The client certificate (newer firmware only)

Since about 2024 VIDAA only lets a phone remote in if it shows Hisense's client certificate, the one
inside Hisense's own phone app. **guest-tv does not include it and never will.** You take it from your own
copy of the app, on your own computer. couch-tv's `scripts/vidaa-cert.py` (github.com/Seagey/couch-tv)
does that from the app's installer file and writes two files:

```
data/vidaa/client.pem
data/vidaa/client.key
```

Put them in guest-tv's `data/vidaa/` folder. Git ignores `data/`. guest-tv reads them from there, never
prints them and never puts them in a log or an error message. Skip this step on older firmware: the first
check below says whether the TV wants it.

### 3. Pair with the PIN

```sh
TV_KIND=vidaa TV_IP=<tv address> .venv/bin/python tools/tv_app.py pair
```

The TV shows a 4 digit PIN. Type it in when asked. The token the TV gives back is kept in `data/` (one
file, only you can read it, never in git).

### 4. Open it

```sh
TV_KIND=vidaa TV_IP=<tv address> .venv/bin/python tools/tv_app.py open
```

guest-tv's welcome page opens in the TV's browser. Then switch the TV off and on: within a few seconds it
opens again.

### 5. The tile (optional, older firmware)

```sh
TV_KIND=vidaa TV_IP=<tv address> .venv/bin/python tools/tv_app.py install
```

This asks the TV to add a **Guest TV** tile to its app row. If the TV refuses, the browser stays the way
in. Nothing else on the TV is touched.

## How the hook works

guest-tv keeps one connection to the TV's MQTT service (port 36669 over TLS, 36668 on older builds) and
looks at it every couple of seconds. The TV says where it is in a field called `statetype`:
`remote_launcher` (VIDAA's home), `livetv`, `sourceswitch` (an input), `remote_setting` (a settings menu),
`fake_sleep_0` (standby) and `fake_sleep_1` (waking). When the TV goes from standby to on and is on its
home or live TV, guest-tv opens the tile, or else the browser at guest-tv's page. Anything else on screen
is left alone, and so is the TV for 20 seconds after a guest's own command. A TV that stops answering for
a few seconds is treated as a Wi-Fi blip, not a switch off.

Only fixed tables reach the TV: keys from a short list, apps only from the TV's own app list, a 4 digit
PIN. Nothing a guest types goes to the TV.

## What is unconfirmed

All of it is written once, in `PROTOCOL` and `KEYS` at the top of `tv_vidaa.py`, so a first report from a
real TV can correct it in one place:

- The name of the request that asks the TV where it is (`gettvstate`).
- That answers come back on `/remoteapp/mobile/<client>/<service>/data/<name>`.
- That keys go to `remote_service` as `sendkey`, and the key names (`KEY_RETURNS` for Back, and Rewind and
  Previous both using `KEY_BACK`).
- The field the PIN travels in, the field the token comes back in, and that the token is the password on
  later logins.
- Which browser the TV lists, and whether `launchapp` opens guest-tv's page in it when given its address.
- Whether the tile, where it installs, survives a firmware update.

## Limits to know

- VIDAA's Home button and home row are VIDAA's. A guest leaving guest-tv with the TV remote's Home button
  is expected.
- The TV's browser may show its own address bar over the page.
- No root, ever. guest-tv will not root a TV or explain how.
- Pairing needs the PIN on the TV once, and newer firmware needs the certificate step. It is a set up, not
  a tap.
- Everything here rests on how the TV is known to behave, not on anything Hisense documents.

## A read only first check

```sh
TV_KIND=vidaa TV_IP=<tv address> .venv/bin/python tools/tv_app.py status
```

It says whether the TV answers, whether it is on, what the TV says is on screen and which guest apps it
found. It sends no key and opens nothing. If it says the TV does not answer, the message says why in plain
words (refused login, no certificate, nothing on the port). Send that sentence, the TV's model and its
VIDAA version (Settings, Support, About) in your report.

## Undo

1. Set `"tv_hook": false` in `data/settings.json` and restart `server.py`.
2. Remove the tile if you added one, the way the TV removes any app.
3. Delete the `vidaa-` file in `data/` (the token) and `data/vidaa/` (the certificate).

Nothing else on the TV was changed.
