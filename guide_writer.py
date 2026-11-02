#!/usr/bin/env python3
"""Write a guest guide (welcome, house rules, how things work, local tips, check-out) with Claude.

The host gives what they have: notes in any shape (a pasted Airbnb guidebook, a messy list, or
nothing) and the area. Claude fills the gaps, checks every local place on the web, and writes
guide JSON for the TV. The host reads it and edits it before guests see it.

    python3 guide_writer.py --area "Byron Bay NSW" --home "a timber lake house for 6" \
        --notes my-notes.md --out data/homes/lake/guide.json

Runs `claude -p` on the host's own Claude login. The API key is removed from its environment,
so a subscription is used, never pay-per-call credits.
"""
import argparse, json, os, re, subprocess, sys

SHAPE = """{
  "welcome": "2 or 3 warm sentences from the host, first person, no cliches",
  "rules": [{"title": "Quiet hours", "body": "one or two plain sentences"}],
  "howto": [{"title": "Fireplace", "body": "short steps"}],
  "local": [
    {"category": "Coffee", "items": [{"name": "real place", "note": "why go, one line", "distance": "5 min drive"}]},
    {"category": "Eat", "items": [{"name": "real place", "note": "...", "distance": "...", "book": "https://its own booking page"}]}
  ],
  "checkout": {"time": "10:00", "steps": ["Strip the beds", "..."]},
  "emergency": [{"name": "Emergency (police, fire, ambulance)", "phone": "000"}]
}"""

PROMPT = """You are writing the guest guide that shows on the TV of a holiday home.

The home: {home}
The area: {area}
The host's own notes (may be empty, may be messy; they win over anything you would guess):
---
{notes}
---

Write JSON only, in exactly this shape:
{shape}

Rules:
- Australian English. No em dashes or en dashes. Short, plain, friendly. Write for a tired guest
  reading a TV from the couch: 1 or 2 sentences per item.
- Every place in "local" must be a real place you have checked with web search is open now and is
  in or near {area}. Guests use this most, so it leads with food and things to do. Categories, in
  this order: "Eat" (4 places for lunch and dinner, a mix of casual and special), "Things to do"
  (4 activities or sights), "Coffee" (3), then 2 or 3 more that fit the area (for example Beaches,
  Walks, Rainy day, Markets, Supplies) with 2 or 3 items each. Each item gets a realistic travel
  time from the home.
- "book" (Eat places only): the page a guest opens to book a table, as linked from the place's own
  website (its own bookings page, or the SevenRooms, OpenTable, Resy or similar page it links to).
  Only a link you actually saw on their site. Leave "book" out for walk-in or phone-only places.
- Never invent a phone number, address, price or opening hour. Leave a field out if you could not
  check it. Emergency numbers: only ones you are sure of (000 in Australia), plus the nearest
  hospital if you checked it.
- "rules" and "howto": use the host's notes first. Where the notes say nothing, write sensible
  defaults for this kind of home and keep them general (the host will edit them).
- This guide shows on the home's TV, and the TV already shows the Wi-Fi name and password, the door
  code and the air conditioning controls. So never say "the Wi-Fi is on the fridge" or "use the wall
  remote": point to the TV (and the phone page its QR code opens) for those.
- 4 to 6 rules, 3 to 6 howto items, 4 to 7 check-out steps.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--notes", help="a text or markdown file with the host's own notes")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="sonnet")
    a = ap.parse_args()

    notes = open(a.notes).read() if a.notes and os.path.exists(a.notes) else ""
    prompt = PROMPT.format(home=a.home, area=a.area, notes=notes.strip() or "(none)", shape=SHAPE)
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)   # subscription, never API credits
    r = subprocess.run(
        ["claude", "-p", prompt, "--model", a.model, "--allowedTools", "WebSearch,WebFetch",
         "--output-format", "text"],
        env=env, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        sys.exit("claude failed: " + (r.stderr or r.stdout)[-800:])
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if not m:
        sys.exit("no JSON in the answer:\n" + r.stdout[-800:])
    guide = json.loads(m.group(0))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(guide, f, indent=2, ensure_ascii=False)
    print("wrote", a.out, "with", sum(len(c.get("items", [])) for c in guide.get("local", [])), "local places")


if __name__ == "__main__":
    main()
