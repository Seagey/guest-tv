"""The Concierge content sync (sanity_sync.py), with no network and no AI: a made-up Sanity
property goes in, and what the TV would show comes out.

    .venv/bin/python tools/sanity_test.py
"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sanity_sync

IE = "+353"   # made-up numbers, built in pieces so the privacy scan sees no phone number here

DOC = {
    "_id": "prop-1", "name": "Test Lodge", "hostPhone": IE + " 00 000 0000", "whatsappNumber": "353" + "890000001",
    "essentials": {"wifiNetwork": "Lodge Guest", "wifiPassword": "no password", "address": "1 Lane, Town",
                   "checkInOut": "Self check-in from 3:00pm with a lockbox · Check-out by 11:30am",
                   "parking": "Out front.", "quietHours": "10:00pm to 7:30am",
                   "additionalNotes": [{"label": "Signal", "text": "Use wifi calling."}]},
    "foodVenues": [
        {"name": "The Inn", "subcategory": ["sitIn", "pubs"], "distance": "6 km", "desc": "Roasts.",
         "mapsLink": "https://maps.example/inn", "secondaryLabel": "Booking", "secondaryLink": "https://inn.example/book"},
        {"name": "Search Only", "subcategory": ["sitIn"], "secondaryLabel": "Booking",
         "secondaryLink": "https://www.google.com/search?q=search+only+booking"}],
    "attractionVenues": [{"name": "Lake Walk", "subcategory": ["walkTrails"], "desc": "A loop."}],
    "travelVenues": [{"name": "Cabs", "subcategory": ["taxi"], "phone": IE + "860000002"}],
    "faqCategories": [
        {"label": "House Rules", "questions": [{"question": "Pets?", "answer": "No."}, {"question": "What are quiet hours?", "answer": "10 to 7:30."}]},
        {"label": "Rooms", "questions": [{"question": "Breakfast?", "answer": "Make your own."}, {"question": "Empty", "answer": ""}]}],
}
passed = failed = 0


def check(name, ok):
    global passed, failed
    print(("PASS " if ok else "FAIL ") + name)
    passed, failed = passed + bool(ok), failed + (not ok)


out = sanity_sync.to_home(DOC)
h, g = out["home"], out["guide"]
check("name and host", h["name"] == "Test Lodge" and h["host"] == "SOS Stays")
check("an open network has no password", h["wifi"] == {"ssid": "Lodge Guest", "password": ""})
check("check-in and check-out times are read from the sentence", (h.get("checkin"), h.get("checkout")) == ("15:00", "11:30"))
check("quiet hours lead the rules, and the FAQ's own quiet hours is not said twice", [r["title"] for r in g["rules"]] == ["Quiet hours", "Pets?"])
check("essentials, notes and FAQs become how-tos, FAQs under their category",
      [(x["title"], x.get("group")) for x in g["howto"]] == [("Check-in and check-out", None), ("Parking", None), ("Address", None), ("Signal", None), ("Breakfast?", "Rooms")])
check("a venue shows under each of its subcategories", [(c["category"], [i["name"] for i in c["items"]]) for c in g["local"]]
      == [("Eat", ["The Inn", "Search Only"]), ("Pubs", ["The Inn"]), ("Walks", ["Lake Walk"]), ("Taxi", ["Cabs"])])
inn, search = g["local"][0]["items"]
check("a real booking page becomes Book a table", inn.get("book") == "https://inn.example/book")
check("a web search is never a booking page", "book" not in search and "link" not in search)
check("phone numbers are spaced the Irish way", g["local"][3]["items"][0]["phone"] == IE + " 86 000 0002")
check("the team's WhatsApp is listed, a row of noughts is not", g["contact"] == [{"name": "SOS Stays, call or WhatsApp", "phone": IE + " 89 000 0001"}])
check("TBD Wi-Fi is left out", "wifi" not in sanity_sync.to_home(dict(DOC, essentials={"wifiNetwork": "TBD", "wifiPassword": "x"}))["home"])

# the cache and the overlay server.py uses
sanity_sync.CACHE = tempfile.mkdtemp(prefix="guest-tv-sanity-")
sanity_sync.fetch = lambda cfg, pid: DOC if pid == "prop-1" else None
home = {"id": "t", "name": "Old name", "checkout": "10:00", "photos": {"hero": "x"}, "sanity": {"property": "prop-1"}}
guide = {"welcome": "Hello.", "emergency": [{"name": "Emergency", "phone": "112"}], "rules": [{"title": "old", "body": "old"}]}
check("no answer yet: the home's own files are used", sanity_sync.overlay("t", home, guide) == (home, guide))
check("first fetch says updated", sanity_sync.sync({}, {"t": home, "plain": {"id": "plain"}}) == {"t": "updated"})
check("the same answer again says same", sanity_sync.sync({}, {"t": home}) == {"t": "same"})
h2, g2 = sanity_sync.overlay("t", home, guide)
check("Sanity wins where it speaks, home.json keeps the rest", h2["name"] == "Test Lodge" and h2["checkout"] == "11:30" and h2["photos"] == {"hero": "x"})
check("guide.json keeps its welcome; Sanity's rules replace the old ones", g2["welcome"] == "Hello." and g2["rules"][0]["title"] == "Quiet hours")
check("the emergency number stays first, then the team", [e["phone"] for e in g2["emergency"]] == ["112", IE + " 89 000 0001"])
check("a property that is gone is an error, and the last answer stays",
      sanity_sync.sync({}, {"t": dict(home, sanity={"property": "nope"})})["t"].startswith("error") and sanity_sync.overlay("t", home, guide)[0]["name"] == "Test Lodge")
check("a cache for another property is not used", sanity_sync.overlay("t", dict(home, sanity={"property": "other"}), guide)[0]["name"] == "Old name")

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
