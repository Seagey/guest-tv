# guest-tv on Fire TV (Vega OS)

A tiny Vega app (React Native for Vega) that shows guest-tv's TV page full screen in Amazon's WebView.
You build it once with Amazon's free tools. Nothing here is a true home screen: Amazon's Home button
still opens Amazon's home, and Home on the Guest remote brings guest-tv back.

Built once, in this order (Mac or Linux, Amazon's Vega tools, a free Amazon Developer account, Developer
Mode on the stick and network access switched on: docs/FIRE-VEGA.md has those steps):

1. `python3 tv-apps/vega/make-config.py http://<this computer's address>:5410 <home id>`
   (writes `src/guest.json`, git ignored; or `TV_KIND=vega TV_IP=<tv address> .venv/bin/python tools/tv_app.py install`)
2. `vega project generate` and name it `guesttv` (a blank app).
3. Copy `src/App.tsx` and `src/guest.json` over that project's `src/`, and add
   `manifest-additions.toml` to its `manifest.toml`.
4. `vega build`, then `vega device install-app --packagePath <the .vpkg> -d <tv address>:5555`.
5. `vega device installed-apps` shows the real app id. If it is not `app.guesttv.home.main`, tell guest-tv.
6. `vega device launch-app --appName <the app id> -d <tv address>:5555`.

The address in `guest.json` has no key in it. To remove: `vega device uninstall-app --appName <the app id>
-d <tv address>:5555`.
