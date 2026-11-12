# guest-tv on a Panasonic Viera TV

## Status: New (Beta)

Checked against a stand in Viera on the computer so far (`tools/panasonic_test.py`), including the
encrypted PIN pairing. First reports from real TVs are wanted. The parts only a real set can settle are
marked UNCONFIRMED in one place, `PROTOCOL` at the top of `tv_panasonic.py`, so a first owner's report can
fix them quickly.

## Which Panasonic TVs

- **My Home Screen Vieras** (about 2015 to 2019) and **older Vieras with network control** (about 2012 on).
- **2018 and newer sets** use the same remote with every command encrypted. You pair once with a PIN
  the TV shows.
- **Not this page:** Panasonic's Google TV models are normal guest-tv Android TVs (README). Its Fire TV,
  Roku and TiVo models run those systems instead.

## What guest-tv does on this TV

My Home Screen does not let anything replace its home screen and runs no Android apps. So the welcome
screen is **a page that opens itself, not a true home screen**:

- The computer that runs guest-tv watches the TV. A few seconds after the TV comes on (a Viera reopens
  its last screen first), it opens guest-tv's welcome page in the TV's own web browser.
- The Guest remote on the guest's phone, and the guest agent, press the TV's buttons, change the volume and
  open apps through the same computer. Nothing is installed on the TV.

| | Panasonic Viera |
|---|---|
| Welcome screen | In the TV's browser, opened by itself just after the TV is switched on |
| TV buttons, volume, mute | Yes. The volume and mute use the TV's real level |
| Open an app (Netflix, YouTube, Stan and so on) | Yes, apps the TV lists, by name |
| A show from the phone | The app opens on its own page and the guest picks the show there |
| Guest profile picker | No |
| Spotify | Just opens |
| Typing, screenshots, which app is on screen | No |

## Set it up

Your AI agent can do this with you. Run each as
`TV_KIND=panasonic TV_IP=<tv address> .venv/bin/python tools/tv_app.py <step>`.

1. **On the TV:** Menu, Network, TV Remote App Settings (the name differs by year). Switch on TV Remote.
   Give the TV a fixed address in your router. Wired works better than Wi-Fi.
2. **`status`** (changes nothing): says whether the TV answers and which apps it lists.
3. **`pair`** (2018 and newer sets only): the TV shows a four digit PIN. Type it in once. A wrong PIN is
   refused: ask for a new one. The keys the TV gives back are kept in `data/` (readable by you only, never in
   git, never printed). Older sets say "no pairing needed".
4. **`open`**: the TV's browser opens guest-tv. From then on it opens by itself each time the TV comes on,
   while `server.py` runs.
5. **`undo`**: set `"tv_hook": false` in `data/settings.json` and restart `server.py`. Delete
   `data/panasonic-<tv address>.key` to forget the pairing. If you switched on TV Remote only for this,
   switch it off again. Nothing else on the TV was changed.

## Honest limits

- The browser's own bar stays visible. A full screen page with no bar is not known to be possible.
- Panasonic's Home button still opens Panasonic's home. Home on the Guest remote brings guest-tv back.
- guest-tv opens only just after the TV is switched on. The TV cannot say what is on screen, so it never
  takes over later and never checks that the page opened.
- A Viera in networked standby may answer on the network. Then guest-tv thinks it is on.
- Wake on LAN and turning the TV on from the phone are not built. Use the TV's own remote.
- All of it rests on how the TV is described publicly, not on anything Panasonic documents for outsiders.
  A firmware update can change it.

## A read only first check

`status` presses nothing and opens nothing. If the TV answers and lists apps, the remote and apps will
work. On a 2018 and newer set, it will say it needs pairing first. When you report back, include the TV's
model number, the year if you know it, and whether it is on Wi-Fi or Ethernet.
