# guest-tv on a Philips TV with Titan OS

**New (Beta).** Checked against a stand in TV on the computer so far (`tools/philips_test.py`), first
reports from real TVs wanted. Philips does not publish the newer parts of its network remote, so some of
this is our best reading and the first real TV will probably show something to fix.

## What guest-tv does on this TV

- **The Guest remote works now.** Keys, volume, mute, and opening the apps the TV lists, from the guest's
  phone. The guest agent works on top of those.
- **The welcome screen needs a Titan app.** Titan OS has no way to replace its home screen and only runs
  web pages that are Titan apps. guest-tv opens a Titan app called **Guest TV** when the TV lists one,
  each time the TV comes on and nothing else is on screen. That app is one you make (below). Until
  there is one, the welcome screen does not open on this TV and the Guest remote is all there is.
- Philips's own Home button still opens Philips's menu. The Guest remote's Home button opens the Guest TV
  app when there is one, and presses the TV's own Home when there is not.

Not possible here: the Guest profile picker (the screen cannot be read), picking a show inside an app
(apps open on their own page and the guest picks), Spotify search (Spotify just opens), screenshots.

A Philips with a Google Assistant button and "Android TV OS" under Settings, About is a Google TV or
Android TV. That is a normal guest-tv Android TV: follow the README, not this page.

Want everything today? Plug a Google TV box into the TV's HDMI and use that.

## Setting it up

You need the computer that runs guest-tv, switched on at home. The owner, or their AI agent, does this
once:

1. **The TV's address.** Settings, Network (or Wireless and networks), Network status. Give the TV a fixed
   address in the router if you can.
2. **The pairing key.** Philips TVs only pair with a remote that signs the PIN with a key from Philips's
   own TV Remote app. guest-tv does not include it: it is Philips's, not ours to hand out. Take it from
   your own copy of the app, then save it on this computer:

   ```sh
   .venv/bin/python tv_philips.py secret
   ```

   It asks for the key without showing it and keeps it in `data/philips-pair-secret.key`, readable only
   by you. Git ignores it. Never paste the key into a chat, an issue or a file in the repository.
3. **Pair.**

   ```sh
   TV_KIND=titan TV_IP=<tv address> .venv/bin/python tools/tv_app.py pair
   ```

   The TV shows a PIN. Type it when asked. The login the TV hands back is kept in
   `data/titan-<tv address>.key`.
4. **Settings.** `"tv_kind": "titan"` next to the TV's address in `data/settings.json`.
5. **The welcome screen (optional).** Make a Titan DevView sandbox app called **Guest TV** (Titan's
   developer app, already on the TV; it needs a Titan Partner Portal developer account) pointing at
   `http://<computer>:5410/titan/?tv=<home>`. `TV_KIND=titan TV_IP=<tv address> .venv/bin/python tools/tv_app.py install`
   prints that address. If DevView will not take a home network address, `tools/tv_app.py build titan`
   makes a copy of the start page with the computer's address filled in, to host anywhere you like. The
   page needs no key: it moves to guest-tv's TV page by itself, or asks once for the computer's address
   with the TV remote.

Check it any time:

```sh
TV_KIND=titan TV_IP=<tv address> .venv/bin/python tools/tv_app.py status
```

Undo: remove the Guest TV app from your sandbox. Nothing else was put on the TV. To stop the computer
opening guest-tv, set `"tv_hook": false` in `data/settings.json` and restart `server.py`.

## What the first tester settles

A short read only first check, after pairing. It presses no key and opens nothing:

- whether the TV answers on port 1926, and on which API version (`system`)
- whether pairing works with our reading of the pairing fields
- what the TV's app list looks like, and whether DevView is in it
- what the TV says is on screen with an app open and with Titan's home open (`activities/current`, not
  confirmed on Titan OS: if the TV will not say, guest-tv opens the Guest TV app after the TV comes on
  and does not check it opened)

Open an issue on GitHub with what you saw, leaving out addresses and keys.

## The honest limits

- Titan OS is mostly sold in Europe and Latin America. Whether JVC, Sharp or HKC Titan TVs answer
  Philips's network remote at all is unknown.
- Titan says DevView is for testing, so the welcome screen is a developer route, like LG's Developer Mode.
  Whether it survives a TV restart is not known.
- Launching a web page over the network (DIAL) is not supported on these TVs, so the computer can only
  open an app the TV already lists.
- Only the apps the TV lists are ever opened, and only by the object the TV itself gave. Nothing a guest
  types reaches the TV.

## How it was written

From protocol facts only: the port, the paths, the field names and the pairing steps, from Philips's own
JointSpace material and couch-tv's notes. Philips's pairing key is never in this repository.
