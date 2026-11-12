# Guest TV for Google TV, Android TV and Fire TV

`guest-tv.apk` puts guest-tv's welcome screen on a Google TV, an Android TV or a Fire TV (Fire OS)
with no computer cables, no ADB and no AI. The owner installs it with the free Downloader app, opens
it, and it finds the guest-tv computer on the Wi-Fi by itself.

It is a cut down copy of couch-tv's TV home app (same author, MIT), with its own id
(`app.guesttv.home`), so it can sit beside couch-tv's app on the same TV.

## Setting up a TV (the owner, with the remote)

1. On the TV, open the app store (Google Play on a Google TV or Android TV, the Amazon Appstore on a
   Fire TV), search for **Downloader** (the free one by AFTVnews) and install it.
2. Open Downloader, type the code **`1061533`** and press **Go**. It points at
   `couchtv.sites.underseage.studio/guest`, which downloads `guest-tv.apk` from the latest release.
   Typing that short link, or the full link
   `github.com/Seagey/guest-tv/releases/latest/download/guest-tv.apk`, works the same way.
3. The first time, Android asks to let Downloader install apps. Press **Settings**, switch Downloader
   on, then press Back. (Fire TV: **Settings, My Fire TV, Developer options, Install unknown apps**,
   Downloader on. If Developer options is missing, open **Settings, My Fire TV, About** and press OK
   on the device's name seven times.)
4. Press **Install**, then **Open**.
5. Guest TV looks for the guest-tv computer on the Wi-Fi for a few seconds and opens the welcome
   page. If it cannot find it, it asks for the computer's address: type the number with the
   on screen keypad or the remote's number keys and press **Connect**.
6. Optional: hold **Back** for a second (or press **Menu** on a Fire TV remote) for Guest TV's
   settings. **Make Guest TV the home screen** opens Android's own "default home app" question.
   Turn on the **Home button watch** only if Home still opens the TV's own home (see below).

The welcome page opens the TV's real apps from its app row, as with couch-tv's app.

## How it finds the computer

guest-tv answers `GET /api/health` with `{"ok": true, "app": "guest-tv"}`. In order:

1. an address a computer passed when starting the app (`--es guest <address>`, so
   `tools/tv_app.py` can still set it over ADB; couch-tv's `--es bridge` works too);
2. the address that worked last time;
3. every address in the TV's own /24 (for a TV at 192.0.2.40, 192.0.2.1 to 192.0.2.254) on port
   5410, 64 at a time with short timeouts, about six seconds at most. Only an answer saying
   `"app": "guest-tv"` counts, so a couch-tv bridge or another web server is passed over;
4. the address form, with **Search again** to look once more.

With more than one home on the computer, the app opens `/tv/` and the computer shows its default
home. `--es tv <home id>` picks another one.

To find the computer's number for the form: on a Mac, **System Settings, Wi-Fi, Details**. A name
ending in `.local` works only on TVs that look such names up; the number always works.

## The Home button watch

Some TVs keep sending the Home button, and the TV at power on, to their own home:

- **Fire TV** always does: Amazon's home cannot be replaced. With the watch on, Amazon's home still
  flashes up for a moment before Guest TV comes back.
- **Google TVs and Android TVs whose own home outranks the default home.** The Android TV emulator
  did this: Android gave Guest TV the home role, and Home still opened its own launcher. Guest TV's
  settings say so when it happens.

The watch is an accessibility service that only sees which app came forward and reads no screen
content. It is off twice over until the owner chooses it: the switch in Guest TV's settings, then
**Guest TV Home button watch** in the TV's **Settings, Accessibility** (on some TVs **Settings,
System, Accessibility**). Android shows its own standard warning about accessibility services when
it is switched on. Guest TV's settings show whether the watch is connected, and have a button that
opens the Accessibility screen.

If Guest TV crashes twice within a few minutes, it stands aside and shows the TV's own home for five
minutes (CrashGuard.kt), and the watch stays out of the way, so a broken app never holds a TV in a loop.

## Building it

```bash
tv-apps/android/build.sh                 # build/guest-tv.apk, looks on port 5410
tv-apps/android/build.sh -Pport=5499     # a test build that looks on another port
.venv/bin/python tools/android_test.py   # the search code's tests, and checks on the built app
```

It needs the Android SDK (`ANDROID_HOME`, else `~/Library/Android/sdk`) and Java 17 or 21. It is
signed with Android's debug key in `~/.android/debug.keystore`, the same key as couch-tv's
releases, so a new build installs over the last. `make-icons.py` redraws the icon and banner
(Pillow). Build output, `.gradle` and `local.properties` are git ignored.

## Limits

- Fire TV: Amazon's home flashes up after Home unless the Home button watch is on, and still for a
  moment with it on. Fire OS 6 runs Amazon's own accessibility manager, and couch-tv found it never
  connects a watch like this one, so on Fire OS 6 Home goes to Amazon's home.
- Google TVs that keep their own home: the Home button watch, as above.
- Fire TVs on Vega OS cannot install APKs at all (guest-tv has a separate Vega app in `tv-apps/vega`).
- The search covers the TV's own /24. On a bigger network where the computer is in another /24, type
  the address once; it is remembered.
- The owner's settings open with a long press of Back, which a guest can find too. They only offer
  the home screen question, the Home button watch and the computer's address.
- No update check: a new version is installed the same way, over the old one.
- Checked so far on an Android TV 12 emulator: the search, the address form, the welcome page and
  its app row, the home screen request and the Home button watch.
