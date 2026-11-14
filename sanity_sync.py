#!/usr/bin/env python3
"""The house guide from Sanity: the same content the SOS Concierge shows, on the TV.

The Concierge web app (github.com/sosstays/concierge) keeps each property in a Sanity project:
its Wi-Fi, address, check-in notes, FAQs and the places to eat, see and travel from. A home that
names its Sanity property gets all of that from there, so the team edits a property once, in the
Concierge Studio, and both the phone concierge and the TV change.

    data/settings.json        "sanity": {"project": "4xk58dqh", "dataset": "production", "every_min": 10}
    data/homes/<id>/home.json "sanity": {"property": "<the property document's _id>"}

    .venv/bin/python sanity_sync.py            # fetch every home now and say what changed
    .venv/bin/python sanity_sync.py --list     # the properties in Sanity and their ids

server.py runs the same fetch every `every_min` minutes. Each answer is kept in data/sanity-cache/
(never in git: it holds the Wi-Fi password), so the TV keeps its content when the internet is down.

What comes from where:
  Sanity      name, Wi-Fi, check-in and check-out times, house rules, how things work (essentials and
              FAQs), local picks, how to reach SOS Stays.
  home.json   the photos, the TV, the weather place, the mode, anything Sanity has no field for.
  guide.json  the welcome words, check-out steps and the emergency number. Sanity wins where it
              has something to say; these fill the gaps.

The dataset is public and read without a token, exactly as the Concierge web app reads it.
"""
import json, os, re, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(DATA, "sanity-cache")
API_VERSION = "2024-06-01"

VENUE = '{name, subcategory, distance, "desc": description, mapsLink, secondaryLabel, secondaryLink, phone}'
PROPERTY = """{
  _id, _updatedAt, name, location, hostPhone, whatsappNumber, checkinMessageTemplate,
  essentials{wifiNetwork, wifiPassword, address, checkInOut, parking, quietHours,
             "additionalNotes": additionalNotes[]{label, text}},
  "foodVenues": foodVenues[]->%s,
  "attractionVenues": attractionVenues[]->%s,
  "travelVenues": travelVenues[]->%s,
  "faqCategories": faqCategories[]{label, "questions": questions[]{question, answer}}
}""" % (VENUE, VENUE, VENUE)

# Sanity's venue subcategories -> the TV's "Around here" lists, in this order.
LOCAL = [("foodVenues", "sitIn", "Eat"), ("foodVenues", "takeaway", "Takeaway"), ("foodVenues", "pubs", "Pubs"),
         ("attractionVenues", "otherAttractions", "Things to do"), ("attractionVenues", "walkTrails", "Walks"),
         ("travelVenues", "train", "Train"), ("travelVenues", "bus", "Bus"), ("travelVenues", "airport", "Airports"),
         ("travelVenues", "taxi", "Taxi")]
PLACEHOLDER = re.compile(r"^\s*(tbd|tbc|todo|n/?a|not set|-+)?\s*$", re.I)
NO_PASSWORD = re.compile(r"^\s*(no password( needed)?|none|open( network)?|no)?\s*$", re.I)   # an open network


def _jread(p, default=None):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def query(cfg, groq, params=None):
    """One GROQ query against the public dataset (no token, like the Concierge web app)."""
    project, dataset = cfg.get("project", ""), cfg.get("dataset", "production")
    if not re.fullmatch(r"[a-z0-9]+", project) or not re.fullmatch(r"[a-z0-9_-]+", dataset):
        raise ValueError('settings.json "sanity" needs a project id and a dataset')
    q = {"query": groq}
    for k, v in (params or {}).items():
        q["$" + k] = json.dumps(v)
    url = "https://%s.apicdn.sanity.io/v%s/data/query/%s?%s" % (project, API_VERSION, dataset, urllib.parse.urlencode(q))
    req = urllib.request.Request(url, headers={"User-Agent": "guest-tv"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read()).get("result")


def fetch(cfg, prop_id):
    return query(cfg, '*[_type == "property" && _id == $id][0]' + PROPERTY, {"id": prop_id})


# ---------------------------------------------------------------- Sanity's words -> the TV's shape

def _text(s):
    return re.sub(r"[ \t]+", " ", str(s or "")).strip()


def _hhmm(text, word):
    """"Check-out by 11:30am" -> "11:30". Only a time written right after the word counts."""
    m = re.search(word + r"[^·|\n.;]{0,24}?\b(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?m\b", text or "", re.I)
    if not m:
        return None
    h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
    return "%02d:%s" % (h, m.group(2) or "00")


def phone_pretty(num):
    """An Irish mobile written as 353 and nine digits, with or without the plus, is spaced for reading
    (plus, 353, then groups of 2, 3 and 4). Anything else is left as typed."""
    d = re.sub(r"\D", "", str(num or ""))
    if not d or not d.strip("0") or re.fullmatch(r"(353)?0+", d):
        return ""   # empty, or a row of noughts someone left as a stand-in
    if d.startswith("353") and len(d) == 12:
        return "+353 %s %s %s" % (d[3:5], d[5:8], d[8:])
    return _text(num) if str(num).strip().startswith("+") else "+" + d


def _place(v):
    it = {"name": _text(v.get("name")), "note": _text(v.get("desc"))}
    if _text(v.get("distance")):
        it["distance"] = _text(v["distance"])
    if phone_pretty(v.get("phone")):
        it["phone"] = phone_pretty(v["phone"])
    if re.match(r"https?://", str(v.get("mapsLink") or "")):
        it["map"] = v["mapsLink"]
    link, label = str(v.get("secondaryLink") or ""), str(v.get("secondaryLabel") or "")
    if re.match(r"https?://", link) and not re.search(r"google\.[a-z.]+/search|facebook\.com/search", link):
        # "book" is what a Book a table button opens, so only a real booking page goes there
        it["book" if re.search(r"book|reserv", label, re.I) else "link"] = link
    return it


def to_home(doc, brand="SOS Stays"):
    """A Sanity property document -> {"home": fields laid over home.json, "guide": laid over guide.json}."""
    e = doc.get("essentials") or {}
    home, guide = {"name": _text(doc.get("name")), "host": brand}, {}
    if not PLACEHOLDER.match(str(e.get("wifiNetwork") or "")):
        pw = str(e.get("wifiPassword") or "").strip()
        home["wifi"] = {"ssid": _text(e["wifiNetwork"]), "password": "" if NO_PASSWORD.match(pw) or PLACEHOLDER.match(pw) else pw}
    for key, word in (("checkin", r"check[- ]?in"), ("checkout", r"check[- ]?out")):
        t = _hhmm(e.get("checkInOut"), word)
        if t:
            home[key] = t
    if _text(e.get("address")):
        home["address"] = _text(e["address"])

    faqs = [(c.get("label") or "", [q for q in (c.get("questions") or []) if q.get("question") and q.get("answer")])
            for c in (doc.get("faqCategories") or [])]
    rules = []
    if _text(e.get("quietHours")):
        rules.append({"title": "Quiet hours", "body": "Please keep noise down from %s." % _text(e["quietHours"])})
    for label, qs in faqs:
        if re.search(r"\brules?\b", label, re.I):
            rules += [{"title": _text(q["question"]), "body": _text(q["answer"])} for q in qs
                      if not (rules and re.search(r"quiet hours", q["question"], re.I))]
    if rules:
        guide["rules"] = rules

    howto = []
    for title, body in (("Check-in and check-out", e.get("checkInOut")), ("Parking", e.get("parking")), ("Address", e.get("address"))):
        if _text(body):
            howto.append({"title": title, "body": _text(body).replace(" · ", ". ")})
    for n in e.get("additionalNotes") or []:
        if _text(n.get("text")):
            howto.append({"title": _text(n.get("label")) or "Good to know", "body": _text(n["text"])})
    for label, qs in faqs:
        if not re.search(r"\brules?\b", label, re.I):
            howto += [{"title": _text(q["question"]), "body": _text(q["answer"]), "group": _text(label)} for q in qs]
    if howto:
        guide["howto"] = howto

    local = []
    for field, sub, title in LOCAL:
        items = [_place(v) for v in (doc.get(field) or []) if v and sub in (v.get("subcategory") or []) and _text(v.get("name"))]
        if items:
            local.append({"category": title, "items": items})
    if local:
        guide["local"] = local

    contact, seen = [], set()
    for label, num in (("%s, call or WhatsApp" % brand, doc.get("whatsappNumber")), ("%s, your host" % brand, doc.get("hostPhone"))):
        p = phone_pretty(num)
        if p and p not in seen:
            seen.add(p)
            contact.append({"name": label, "phone": p})
    if contact:
        guide["contact"] = contact
    wa = re.sub(r"\D", "", str(doc.get("whatsappNumber") or ""))
    if wa.strip("0"):
        home["whatsapp"] = wa
    return {"home": home, "guide": guide, "updated": doc.get("_updatedAt"), "property": doc.get("_id")}


# ---------------------------------------------------------------- the cache server.py reads

def cache_file(hid):
    return os.path.join(CACHE, re.sub(r"[^a-z0-9-]", "", hid) + ".json")


def overlay(hid, home, guide):
    """Lay the last Sanity answer for this home over home.json and guide.json. No answer yet: unchanged."""
    c = _jread(cache_file(hid)) if (home.get("sanity") or {}).get("property") else None
    if not c or c.get("property") != home["sanity"]["property"]:
        return home, guide
    home, guide = dict(home, **c.get("home", {})), dict(guide)
    for k, v in (c.get("guide") or {}).items():
        if k == "contact":   # the house's own emergency numbers first, then how to reach the team
            guide["emergency"] = list(guide.get("emergency") or []) + v
        else:
            guide[k] = v
    return home, guide


def sync(cfg, homes, brand="SOS Stays"):
    """Fetch every home that names a Sanity property. `homes` is {home id: home.json}.
    Returns {home id: "updated" | "same" | "error: ..."} and never raises: an old answer stays in use."""
    out = {}
    os.makedirs(CACHE, exist_ok=True)
    for hid, h in homes.items():
        pid = (h.get("sanity") or {}).get("property")
        if not pid:
            continue
        try:
            doc = fetch(cfg, pid)
            if not doc:
                out[hid] = "error: no property %s in Sanity" % pid
                continue
            new = to_home(doc, brand)
            old = _jread(cache_file(hid)) or {}
            same = {k: old.get(k) for k in ("home", "guide", "property")} == {k: new[k] for k in ("home", "guide", "property")}
            new["fetched"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            tmp = cache_file(hid) + ".tmp"
            with open(tmp, "w") as f:
                json.dump(new, f, indent=2, ensure_ascii=False)
            os.replace(tmp, cache_file(hid))
            out[hid] = "same" if same else "updated"
        except Exception as ex:
            out[hid] = "error: %s" % ex
    return out


def main():
    settings = _jread(os.path.join(DATA, "settings.json"), {}) or {}
    cfg = settings.get("sanity") or {}
    if "--list" in sys.argv:
        for p in query(cfg, '*[_type == "property"] | order(name asc){_id, name}') or []:
            print("%s  %s" % (p["_id"], p.get("name")))
        return
    homes = {}
    for hid in sorted(os.listdir(os.path.join(DATA, "homes"))):
        h = _jread(os.path.join(DATA, "homes", hid, "home.json"))
        if h:
            homes[hid] = h
    res = sync(cfg, homes, (settings.get("brand") or {}).get("name", "SOS Stays"))
    for hid, r in res.items():
        c = _jread(cache_file(hid)) or {}
        g = c.get("guide") or {}
        print("%-18s %s  (%d rules, %d how-tos, %d local picks)" % (
            hid, r, len(g.get("rules", [])), len(g.get("howto", [])), sum(len(x["items"]) for x in g.get("local", []))))
    if not res:
        print('No home names a Sanity property yet ("sanity": {"property": "<_id>"} in its home.json).')
    if any(r.startswith("error") for r in res.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
