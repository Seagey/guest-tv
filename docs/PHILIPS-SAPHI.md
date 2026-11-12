# guest-tv on an older Philips TV (Saphi)

**New (Beta).** Checked against a stand in TV on the computer so far (`tools/philips_test.py`), first
reports from real TVs wanted. **It depends on the model and the firmware.** Some of these TVs answer
Philips's network remote with no pairing at all, some want a PIN, and some are reported to have no network
remote at all. The read only check below tells you which one you have.

## What guest-tv does on this TV

- **The Guest remote:** keys, volume, mute, and (where the TV lists them) opening apps. Many Saphi sets
  list no apps, and then the Guest remote is the arrows, OK, Back, play and pause, and volume.
- **The welcome screen, if the TV offers a browser to its network remote.** guest-tv's page opens in the
  TV's own browser each time the TV comes on and nothing else is on screen. The browser's own bar can
  show, an old browser may draw parts of the page slowly or plainly, and Philips's Home button still opens
  Philips's menu. The Guest remote's Home button brings the page back. With no browser, there is no
  welcome screen and the Guest remote is all there is.

Not possible here: the Guest profile picker, picking a show inside an app, Spotify search (Spotify just
opens), screenshots.

Philips Android TV and Google TV models are normal guest-tv Android TVs: follow the README. A Philips with
no Google button and a home of "Lifestyle" rows is Titan OS: see [PHILIPS-TITAN.md](PHILIPS-TITAN.md).

## Setting it up

You need the computer that runs guest-tv, switched on at home.

1. **The TV's address.** Settings, Wireless and networks (or Network), View network settings. Give the TV
   a fixed address in the router if you can.
2. **Check it** (reads only, presses no key, opens nothing):

   ```sh
   TV_KIND=saphi TV_IP=<tv address> .venv/bin/python tools/tv_app.py status
   ```

   It tries plain port 1925 first. If the TV answers without a login, nothing needs pairing. If it asks
   for one, or answers only on 1926, pair it as in [PHILIPS-TITAN.md](PHILIPS-TITAN.md) steps 2 and 3
   (a PIN, and your own pairing key).
3. **Settings.** `"tv_kind": "saphi"` next to the TV's address in `data/settings.json`.
4. **Open it** (this puts a page on the TV, so do it with someone at the TV):

   ```sh
   TV_KIND=saphi TV_IP=<tv address> .venv/bin/python tools/tv_app.py open
   ```

   Nothing is installed on the TV, so there is nothing to undo. To stop the computer opening the page,
   set `"tv_hook": false` in `data/settings.json` and restart `server.py`.

**Security.** A set that answers without a login can already be driven by anything on your Wi-Fi.
guest-tv does not change that and cannot switch it off. A guest Wi-Fi for visitors keeps them off the
TV's port.

## What is known, and from where

Nothing here has been seen on a real Saphi set by guest-tv yet, so each line is a reading until a tester's
output settles it. The same guesses sit in `PROTOCOL` in `tv_philips.py`, so one change fixes them.

| What | Status |
|---|---|
| Non Android Philips sets answer `http://<tv>:1925/<version>/...` with no pairing and no login | Reading |
| The version is `1`, `5` or `6` depending on the model | Reading |
| An answer to `audio/volume` with no login means no pairing is needed | Our reading (Android sets guard it) |
| `system` lists `browser` in an `activities` list when there is a browser | Reading, one v1 answer in public notes |
| `POST activities/browser {"url": ...}` opens that page in the TV's browser | Reading, no report of it working |
| A set with no `powerstate` path counts as on while it answers | Our reading |
| `activities/current` can fail or answer oddly | Expected: guest-tv treats it as unknown, and after it opens the page it does not check |
| Wake on LAN switches on a set in deep standby | Not every set does |

## What the first tester settles

Whether the set answers on 1925 without a login, on which version, whether it lists a browser, and, with
`open`, whether the browser really shows guest-tv's page. Open an issue on GitHub with what you saw,
leaving out addresses.

## How it was written

From protocol facts only: the port, the paths and the field names, from public notes and couch-tv's own
notes. Philips's pairing key is never in this repository.
