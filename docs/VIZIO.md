# guest-tv on a VIZIO TV (SmartCast and VIZIO OS)

## Status: New (Beta)

Checked against a stand in VIZIO on the computer so far (`tools/vizio_test.py`), first reports from real
TVs wanted. The driver (`tv_vizio.py`) is cut down from couch-tv's VIZIO driver, which was written from
VIZIO's own public app list and public notes on the SmartCast API. If you have a VIZIO, you would be among
the first: please run the first check below and [open an issue](https://github.com/Seagey/guest-tv/issues)
with what it printed.

## What guest-tv does on a VIZIO

**The Guest remote on the guest's phone, and nothing on the TV screen.** Everything that lives on the phone
works exactly as on any other TV: the Guest remote, the guest agent, aircon, lights, pool, the house guide.

On the TV itself, from the phone:

- The arrows, OK and Back.
- Home, which presses VIZIO's own Home (see "The welcome screen" below).
- Play and pause, next and previous, rewind and fast forward.
- Volume up, volume down and mute.
- Opening Netflix, YouTube, Prime Video, Disney+, Paramount+ and Apple TV.
- The agent's "put on Netflix" and "turn it down".

## What it cannot do

| | VIZIO |
|---|---|
| The welcome screen on the TV | **No.** See below |
| Guest profile picker in streaming apps | No (there is no way to read the screen) |
| Typing from the phone | No |
| Opening a show | The app opens on its own page and the guest picks the show. No way to open a title directly is known on a VIZIO |
| Spotify search | Spotify just opens (and it is not on every VIZIO) |
| Which app is on screen | Where the TV says. No title, no progress |
| Stan, Binge, ABC iview, 9Now, 7plus, 10play, Kayo, SBS On Demand | Not on VIZIO's app list: VIZIO sells TVs in the US, Canada and Mexico |
| Screenshots | No |

## The welcome screen

guest-tv's welcome page cannot be opened on a VIZIO, for free, today:

- **No browser.** VIZIO OS has no web browser to open the page in.
- **No sideloading.** There is no developer mode that installs an outside app.
- **VIZIO's app programme is a closed partner scheme.** An app on the TV's row means a business deal with
  VIZIO, not a download.
- **Chromecast built in only opens registered receivers.** A Cast receiver is a web page Google has
  registered. Nobody has shown a VIZIO opening a receiver that is not a known one.

So the driver says so plainly (`can_open` is off, `open_guest_app` gives a clear sentence), the switch on
hook does nothing, and Home on the Guest remote presses VIZIO's own Home. Guests who scan nothing on the TV
can still be given the Guest remote address another way (a card in the house, the booking message).

couch-tv's docs describe one open experiment, showing a page through Cast dashboards. guest-tv has no code
for it, and it is not a feature here.

## Which VIZIO TVs

- **VIZIO OS** (2024 on, and some Onn TVs sold by Walmart) and **SmartCast** with firmware 4.0 or newer:
  the TV answers on port 7345.
- **Older SmartCast** firmware: port 9000.

The driver tries 7345, then 9000, and keeps whichever answers like a VIZIO. A firmware update can change
any of this.

## Set it up

You, or your AI agent, do this once. Replace `<tv address>` with the TV's address on your Wi-Fi (give it a
fixed address in your router, so it does not change).

1. **On the TV:** set the power mode to **Quick Start** (not Eco) if you want the Guest remote to turn the
   TV on. In Eco mode the TV drops off the network when it is off.
2. **Tell guest-tv about the TV:** run `setup.py` and choose VIZIO, or set `"tv_kind": "vizio"` next to the
   TV's address in `data/settings.json`.
3. **First check, read only** (it sends no key and opens nothing):

   ```sh
   TV_KIND=vizio TV_IP=<tv address> .venv/bin/python tools/tv_app.py status
   ```

   Before pairing, a VIZIO answers "wants pairing first" to most things. That is expected.
4. **Pair.** The TV shows a 4 digit PIN on its screen:

   ```sh
   TV_KIND=vizio TV_IP=<tv address> .venv/bin/python tools/tv_app.py pair
   ```

   Type the PIN in when asked. The token the TV gives back is kept in `data/` (only you can read it, and
   git ignores it). It is never printed or logged.
5. **Check again:** run `status` once more. It should say the TV is on (or in standby), and list the apps.
6. **Try the Guest remote** on a phone: an arrow, OK, volume up once, Home, then open Netflix.

There is no `install` step on a VIZIO, because there is no TV side app to put on it.

## Apps

VIZIO keeps its app list in its own cloud, not on the TV, so guest-tv cannot ask the TV which apps it has.
It carries the ids from VIZIO's own public app list (read 12 November 2026). None has been opened on a real
VIZIO yet.

| App | Name space | App id |
|---|---|---|
| Netflix | 3 | 1 |
| YouTube | 5 | 1 |
| Prime Video | 2 | 4 |
| Disney+ | 2 | 75 |
| Paramount+ | 2 | 37 |
| Apple TV | 3 | 4 |

## What is not confirmed yet

Everything is written once at the top of `tv_vizio.py`, so a tester's report can correct it in one place.
Two public references agree on the paths for pairing, power, keys, app launch. These rest on one source or
our own reading:

- The key codes other than volume and power: the arrows, OK, Back, Home, play and pause.
- That the power state is 1 for on and 0 for standby.
- `/app/current` and the shape of its answer, and that VIZIO's own home answers as name space 4, app id 1.
- What a token the TV no longer accepts looks like.
- That launching wants `MESSAGE` as null.

## Limits to know

- This is a phone remote. The TV screen shows VIZIO's own screens, never guest-tv's.
- Pairing needs the PIN on the TV once. If the TV is reset, or forgets guest-tv, pair again.
- Everything here rests on public notes about the SmartCast API, not on anything VIZIO publishes for outside
  developers. A firmware update can break it.
- Never open a router port for the TV's SmartCast port: some of its requests need no token.

## Undo

1. Take `"tv_kind": "vizio"` out of `data/settings.json` (or set `"tv_hook": false`).
2. Delete `data/vizio-<tv address>.key` (the token).
3. Optional: on the TV, remove guest-tv from its list of paired devices, if your model shows one.
