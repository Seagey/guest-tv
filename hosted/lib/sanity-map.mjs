// A Concierge property document -> the TV's shape. The same mapping as sanity_sync.py (to_home and
// overlay), in JavaScript, so the hosted screen and the house computer show the same thing.
// Change one, change the other, and run tools/sanity_test.py and hosted/test.mjs.

const VENUE = '{name, subcategory, distance, "desc": description, mapsLink, secondaryLabel, secondaryLink, phone}';
export const PROPERTY = `{
  _id, _updatedAt, name, location, hostPhone, whatsappNumber, checkinMessageTemplate,
  essentials{wifiNetwork, wifiPassword, address, checkInOut, parking, quietHours,
             "additionalNotes": additionalNotes[]{label, text}},
  "foodVenues": foodVenues[]->${VENUE},
  "attractionVenues": attractionVenues[]->${VENUE},
  "travelVenues": travelVenues[]->${VENUE},
  "faqCategories": faqCategories[]{label, "questions": questions[]{question, answer}}
}`;

// Sanity's venue subcategories -> the TV's "Around here" lists, in this order.
const LOCAL = [["foodVenues", "sitIn", "Eat"], ["foodVenues", "takeaway", "Takeaway"], ["foodVenues", "pubs", "Pubs"],
  ["attractionVenues", "otherAttractions", "Things to do"], ["attractionVenues", "walkTrails", "Walks"],
  ["travelVenues", "train", "Train"], ["travelVenues", "bus", "Bus"], ["travelVenues", "airport", "Airports"],
  ["travelVenues", "taxi", "Taxi"]];
const PLACEHOLDER = /^\s*(tbd|tbc|todo|n\/?a|not set|-+)?\s*$/i;
const NO_PASSWORD = /^\s*(no password( needed)?|none|open( network)?|no)?\s*$/i;   // an open network

const text = (s) => String(s == null ? "" : s).replace(/[ \t]+/g, " ").trim();

// "Check-out by 11:30am" -> "11:30". Only a time written right after the word counts.
function hhmm(str, word) {
  const m = new RegExp(word + "[^·|\\n.;]{0,24}?\\b(\\d{1,2})(?:[:.](\\d{2}))?\\s*([ap])\\.?m\\b", "i").exec(str || "");
  if (!m) return null;
  const h = (parseInt(m[1], 10) % 12) + (m[3].toLowerCase() === "p" ? 12 : 0);
  return String(h).padStart(2, "0") + ":" + (m[2] || "00");
}

// An Irish mobile written as 353 and nine digits is spaced for reading. Anything else is left as typed.
export function phonePretty(num) {
  const d = String(num == null ? "" : num).replace(/\D/g, "");
  if (!d || !d.replace(/^0+|0+$/g, "") || /^(353)?0+$/.test(d)) return "";
  if (d.startsWith("353") && d.length === 12) return `+353 ${d.slice(3, 5)} ${d.slice(5, 8)} ${d.slice(8)}`;
  return String(num).trim().startsWith("+") ? text(num) : "+" + d;
}

function place(v) {
  const it = { name: text(v.name), note: text(v.desc) };
  if (text(v.distance)) it.distance = text(v.distance);
  if (phonePretty(v.phone)) it.phone = phonePretty(v.phone);
  if (/^https?:\/\//.test(String(v.mapsLink || ""))) it.map = v.mapsLink;
  const link = String(v.secondaryLink || ""), label = String(v.secondaryLabel || "");
  if (/^https?:\/\//.test(link) && !/google\.[a-z.]+\/search|facebook\.com\/search/.test(link)) {
    it[/book|reserv/i.test(label) ? "book" : "link"] = link;
  }
  return it;
}

/** A Sanity property document -> {home: fields laid over home.json, guide: laid over guide.json}. */
export function toHome(doc, brand = "SOS Stays") {
  const e = doc.essentials || {};
  const home = { name: text(doc.name), host: brand }, guide = {};
  if (!PLACEHOLDER.test(String(e.wifiNetwork || ""))) {
    const pw = String(e.wifiPassword || "").trim();
    home.wifi = { ssid: text(e.wifiNetwork), password: NO_PASSWORD.test(pw) || PLACEHOLDER.test(pw) ? "" : pw };
  }
  for (const [key, word] of [["checkin", "check[- ]?in"], ["checkout", "check[- ]?out"]]) {
    const t = hhmm(e.checkInOut, word);
    if (t) home[key] = t;
  }
  if (text(e.address)) home.address = text(e.address);

  const faqs = (doc.faqCategories || []).map((c) => [c.label || "", (c.questions || []).filter((q) => q.question && q.answer)]);
  const rules = [];
  if (text(e.quietHours)) rules.push({ title: "Quiet hours", body: `Please keep noise down from ${text(e.quietHours)}.` });
  for (const [label, qs] of faqs) {
    if (/\brules?\b/i.test(label)) {
      for (const q of qs) {
        if (!(rules.length && /quiet hours/i.test(q.question))) rules.push({ title: text(q.question), body: text(q.answer) });
      }
    }
  }
  if (rules.length) guide.rules = rules;

  const howto = [];
  for (const [title, body] of [["Check-in and check-out", e.checkInOut], ["Parking", e.parking], ["Address", e.address]]) {
    if (text(body)) howto.push({ title, body: text(body).split(" · ").join(". ") });
  }
  for (const n of e.additionalNotes || []) {
    if (text(n.text)) howto.push({ title: text(n.label) || "Good to know", body: text(n.text) });
  }
  for (const [label, qs] of faqs) {
    if (!/\brules?\b/i.test(label)) for (const q of qs) howto.push({ title: text(q.question), body: text(q.answer), group: text(label) });
  }
  if (howto.length) guide.howto = howto;

  const local = [];
  for (const [field, sub, title] of LOCAL) {
    const items = (doc[field] || []).filter((v) => v && (v.subcategory || []).includes(sub) && text(v.name)).map(place);
    if (items.length) local.push({ category: title, items });
  }
  if (local.length) guide.local = local;

  const contact = [], seen = new Set();
  for (const [label, num] of [[`${brand}, call or WhatsApp`, doc.whatsappNumber], [`${brand}, your host`, doc.hostPhone]]) {
    const p = phonePretty(num);
    if (p && !seen.has(p)) { seen.add(p); contact.push({ name: label, phone: p }); }
  }
  if (contact.length) guide.contact = contact;
  const wa = String(doc.whatsappNumber || "").replace(/\D/g, "");
  if (wa.replace(/^0+|0+$/g, "")) home.whatsapp = wa;
  return { home, guide, updated: doc._updatedAt, property: doc._id };
}

/** Lay a Sanity answer over home.json and guide.json (sanity_sync.overlay). */
export function overlay(home, guide, mapped) {
  if (!mapped) return { home, guide };
  const h = { ...home, ...mapped.home }, g = { ...guide };
  for (const [k, v] of Object.entries(mapped.guide || {})) {
    if (k === "contact") g.emergency = [...(g.emergency || []), ...v];   // the house's own emergency numbers first
    else g[k] = v;
  }
  return { home: h, guide: g };
}
