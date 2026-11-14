# guest-tv, hosted

The welcome screen on the internet, with no computer in the house. The TV (a Google TV stick or a
TV with Google TV built in) opens one address and shows the same page the house computer serves.

    https://sos-guest-tv.netlify.app/<home id>        for example /rathescar-grove

## What it shows, and from where

| Where | What |
|---|---|
| Sanity, Concierge project (`4xk58dqh`, public, read only) | name, Wi-Fi, check-in and check-out, rules, how things work, local picks, phone numbers |
| Sanity, Guest TV project (`p0aigdqj`, private) | the default welcome video for each home, and a welcome for one guest (name, dates, video, message) |
| `data/homes/<id>/home.json` and `guide.json` in this repo | the photos, the weather place, the welcome words, the emergency number |

Edit videos and guest welcomes at https://sos-guest-tv.sanity.studio/. The TV follows within about
a minute for videos and five minutes for property content.

## The welcome video

- A home's **Default welcome video** plays for every guest.
- A **Guest welcome** with dates that include today wins: its video plays instead, its first name
  goes in the greeting, and its message replaces the welcome words.
- It plays full screen. **OK** or **Back** closes it. A **Welcome video** button on the home plays
  it again.
- "How often it plays by itself" on the home: once a day, every time the TV comes on, or never.
- TV browsers often refuse sound until a button is pressed. Then it starts silent and says
  "OK sound on".
- Add `?video=1` to the address to play it now, `?video=0` to keep it quiet (for testing).

## What is not here

No TV control, no Guest remote, no Ask agent, no aircon or lights: those need the house computer
(the main README). No booking calendar yet: every home shows the open welcome, with a guest's name
only when a Guest welcome is set for their dates.

## Build, try, deploy

```bash
cd hosted
npm install
node build.mjs                 # writes dist/ (the site) and .deploy/ (the folder to upload)
node dev.mjs                   # http://localhost:8899/rathescar-grove
node test.mjs parity.json      # the JavaScript mapping against sanity_sync.py (see test.mjs)
```

Deploy by uploading `.deploy/` to the Netlify project `sos-guest-tv`. `.deploy/` holds only public
files: no `data/private.json`, no Wi-Fi password (that is read from Sanity when the page asks).
The function needs one environment variable in Netlify, `SANITY_TV_READ_TOKEN` (a read token for
the Guest TV project). `/api/health` says whether it can read that project.

A new home: add `data/homes/<id>/` with a `home.json` that names its Concierge property, add a
**TV home** in the Studio with the same home id, build and deploy.

`lib/sanity-map.mjs` is `sanity_sync.to_home` in JavaScript. Change one, change the other.
