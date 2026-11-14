// guest-tv, hosted: what server.py answers on the house computer, for the TV and phone pages on the
// internet. Read only. Property content comes from the Concierge's Sanity project (public, no token);
// welcome videos come from the Guest TV Sanity project (read token in SANITY_TV_READ_TOKEN).
// No TV control, no Guest remote and no agent here: those need the house computer.
import type { Config, Context } from "@netlify/functions";
import QRCode from "qrcode";
import { HOMES, SETTINGS } from "../../lib/homes.generated.mjs";
import { PROPERTY, overlay, toHome } from "../../lib/sanity-map.mjs";

const API_VERSION = "2024-06-01";
const TV_PROJECT = "p0aigdqj";   // Sanity project "Guest TV": tvHome and guestVideo documents
const TV_DATASET = "production";

type Json = Record<string, any>;
const cache = new Map<string, { at: number; data: any }>();

/** Keep an answer for `secs`; if the fetch fails, the last good answer stays in use. */
async function cached<T>(key: string, secs: number, get: () => Promise<T>, fallback: T): Promise<T> {
  const c = cache.get(key);
  if (c && Date.now() - c.at < secs * 1000) return c.data;
  try {
    const data = await get();
    cache.set(key, { at: Date.now(), data });
    return data;
  } catch (e) {
    console.error(key, String(e));
    return c ? c.data : fallback;
  }
}

async function groq(project: string, dataset: string, query: string, params: Json, token?: string) {
  const q = new URLSearchParams({ query, perspective: "published" });
  for (const [k, v] of Object.entries(params)) q.set("$" + k, JSON.stringify(v));
  const host = token ? "api" : "apicdn";   // a private dataset is not on the CDN
  const r = await fetch(`https://${project}.${host}.sanity.io/v${API_VERSION}/data/query/${dataset}?${q}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal: AbortSignal.timeout(10000),
  });
  if (!r.ok) throw new Error(`Sanity ${project}: ${r.status}`);
  return (await r.json()).result;
}

function todayIn(tz: string) {
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

/** The welcome video for this home today: one made for the guest who is staying, else the default. */
async function videoFor(id: string, today: string) {
  const token = Netlify.env.get("SANITY_TV_READ_TOKEN") || undefined;
  const r = await cached("tv:" + id + ":" + today, 60, () => groq(TV_PROJECT, TV_DATASET, `{
    "home": *[_type == "tvHome" && homeId == $id][0]{videoSound, videoEvery, "video": defaultVideo.asset->{_id, url}},
    "guest": *[_type == "guestVideo" && home->homeId == $id && from <= $today && to >= $today] | order(from desc)[0]{
      guestName, from, to, message, "video": video.asset->{_id, url}}
  }`, { id, today }, token), null as any);
  const home = (r && r.home) || {}, guest = (r && r.guest) || null;
  const asset = (guest && guest.video) || home.video;
  return {
    guest,
    video: asset && asset.url ? {
      url: asset.url, id: asset._id, kind: guest && guest.video ? "guest" : "default",
      sound: home.videoSound !== false, every: home.videoEvery || "day",
    } : null,
  };
}

async function state(id: string, origin: string) {
  const base = (HOMES as Json)[id];
  if (!base) return null;
  const brand = (SETTINGS as Json).brand || {};
  const sanity = (SETTINGS as Json).sanity || {};
  const mapped = await cached("prop:" + id, 300, async () => {
    const doc = await groq(sanity.project, sanity.dataset || "production",
      '*[_type == "property" && _id == $id][0]' + PROPERTY, { id: base.home.sanity.property });
    return doc ? toHome(doc, brand.name || "SOS Stays") : null;
  }, null as any);
  const { home: h, guide: g } = overlay(base.home, base.guide || {}, mapped);
  const tz = (h.weather || {}).tz || ((SETTINGS as Json).weather || {}).tz || "UTC";
  const tv = await videoFor(id, todayIn(tz));
  const guestRoom = h.mode === "guest";
  // No booking feed here yet: the welcome, Wi-Fi and guide always show ("stay_open" in home.json).
  // A guest welcome in Sanity adds the guest's first name for their dates.
  const stay = { phase: "open", guest: (tv.guest && tv.guest.guestName) || "", active: true };
  return {
    id, mode: h.mode || "stay", demo: false, name: h.name, kind: h.kind, host: h.host,
    photos: h.photos || {}, scene: h.scene || {}, stay, checkin: h.checkin, checkout_time: h.checkout,
    wifi: h.wifi || null, access: [],
    welcome: (tv.guest && tv.guest.message) || g.welcome || "",
    rules: guestRoom ? [] : g.rules || [], howto: g.howto || [], local: g.local || [],
    checkout: guestRoom ? {} : g.checkout || {}, emergency: g.emergency || [], notes: h.notes || [],
    phone_url: `${origin}/p/?home=${id}`, address: h.address, whatsapp: h.whatsapp,
    brand, has_climate: false, remote_url: null, video: tv.video, hosted: true,
    homes: Object.entries(HOMES as Json).map(([i, x]: [string, any]) => ({ id: i, name: x.home.name || i })),
  };
}

async function weather(id: string) {
  const base = (HOMES as Json)[id];
  const w = (base && base.home.weather) || (SETTINGS as Json).weather;
  if (!w || w.lat == null) return { ok: false, place: "" };
  return cached("wx:" + w.lat + "," + w.lon, 1800, async () => {
    const q = new URLSearchParams({
      latitude: String(w.lat), longitude: String(w.lon), timezone: w.tz || "auto", forecast_days: "7",
      current: "temperature_2m,weather_code,is_day",
      daily: "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
    });
    const r = await fetch("https://api.open-meteo.com/v1/forecast?" + q, { signal: AbortSignal.timeout(10000) });
    if (!r.ok) throw new Error("weather " + r.status);
    const d = await r.json(), dl = d.daily;
    return {
      ok: true, place: w.place,
      now: { temp: Math.round(d.current.temperature_2m), code: d.current.weather_code, day: d.current.is_day },
      days: dl.time.map((t: string, i: number) => ({
        date: t, code: dl.weather_code[i], hi: Math.round(dl.temperature_2m_max[i]), lo: Math.round(dl.temperature_2m_min[i]),
        rain: dl.precipitation_probability_max[i], sunrise: dl.sunrise[i].slice(-5), sunset: dl.sunset[i].slice(-5),
      })),
    };
  }, { ok: false, place: w.place } as any);
}

function wifiQr(w: Json) {
  const esc = (s: string) => String(s || "").replace(/([\\;,:"])/g, "\\$1");
  if (!w.password) return `WIFI:T:nopass;S:${esc(w.ssid)};;`;   // an open network: the phone joins with no password asked
  return `WIFI:T:WPA;S:${esc(w.ssid)};P:${esc(w.password)};;`;
}

const json = (body: any, status = 200, maxAge = 0) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json", "Cache-Control": maxAge ? `public, max-age=${maxAge}` : "no-store" },
});

export default async (req: Request, _context: Context) => {
  const url = new URL(req.url);
  const path = url.pathname.replace(/\/+$/, "");
  const id = url.searchParams.get("home") || (SETTINGS as Json).default_home;

  if (path === "/api/health") {   // is the Guest TV project readable from here? (says yes or why not, never the token)
    let tv = "ok";
    try {
      await groq(TV_PROJECT, TV_DATASET, 'count(*[_type == "tvHome"])', {}, Netlify.env.get("SANITY_TV_READ_TOKEN") || undefined);
    } catch (e) { tv = String(e); }
    return json({ ok: tv === "ok", hosted: true, token: !!Netlify.env.get("SANITY_TV_READ_TOKEN"), guest_tv: tv });
  }
  if (path === "/api/log") {   // the TV page reports its own script errors here (TVs have no console to look at)
    if (req.method === "POST") console.log("tv page:", (await req.text()).slice(0, 600));
    return json({ ok: true });
  }
  if (req.method !== "GET") return json({ ok: false, error: "This screen is read only. Change it in Sanity." }, 405);

  if (path === "/api/state") {
    const s = await state(id, url.origin);
    return s ? json(s) : json({ error: "No home called " + id }, 404);
  }
  if (path === "/api/weather") return json(await weather(id), 200, 600);
  if (path === "/api/qr") {
    const s = await state(id, url.origin);
    if (!s) return json({ error: "No home called " + id }, 404);
    const what = url.searchParams.get("what");
    if (what === "remote") return json({ error: "no remote here" }, 404);
    if (what === "wifi" && !(s.wifi && s.wifi.ssid)) return json({ error: "no wifi now" }, 404);
    const svg = await QRCode.toString(what === "wifi" ? wifiQr(s.wifi) : s.phone_url,
      { type: "svg", errorCorrectionLevel: "M", margin: 2, color: { dark: "#111111", light: "#ffffff" } });
    return new Response(svg, { headers: { "Content-Type": "image/svg+xml", "Cache-Control": "no-store" } });
  }
  // the parts that need the house computer: say so in the shape the pages expect
  if (path === "/api/aircon") return json({ connected: false, zones: [] });
  if (path === "/api/hub") return json({ rooms: [], speakers: [], pool: null });
  if (path === "/api/tv/apps") return json({ apps: [] });
  return json({ error: "not found" }, 404);
};

export const config: Config = { path: "/api/*" };
