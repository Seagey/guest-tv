#!/usr/bin/env python3
"""Write tv-apps/vega/src/guest.json for guest-tv's Vega app: where guest-tv is, and which home.

    python3 tv-apps/vega/make-config.py http://<this computer's address>:5410 <home id>

No key goes in the file. It holds this computer's address on your network, so it is git ignored.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def build(url, home_id):
    if not re.fullmatch(r"http://[\w.:-]+", url or ""):
        raise SystemExit("the guest-tv address looks like http://<computer address>:5410 (no path)")
    if not re.fullmatch(r"[a-z0-9-]{1,40}", home_id or ""):
        raise SystemExit("the home id is lower case letters, digits and - only")
    return {"url": url, "tv": home_id}


def write(cfg):
    path = os.path.join(HERE, "src", "guest.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
    return path


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    print("wrote", os.path.relpath(write(build(sys.argv[1], sys.argv[2]))))
