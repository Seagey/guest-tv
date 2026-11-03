"""Smart lights, the pool, speakers and the host's own actions, for the Guest remote and the guest agent.

Lights, in data/settings.json (or a home's home.json, which wins):

    "lights": {"kind": "home_assistant", "url": "http://homeassistant.local:8123",
               "rooms": {"Bed 3": ["light.bed_3_lamp", "light.bed_3_ceiling"]}}
    "lights": {"kind": "hue", "bridge": "<hue-bridge-ip>", "rooms": {"Bed 3": ["4", "7"]}}
    "lights": {"kind": "demo", "rooms": {"Bed 3": ["lamp"]}}

The Home Assistant token (`ha_token`) and the Hue bridge user (`hue_user`) live in data/private.json.
Home Assistant covers Hue, LIFX, TP-Link, Govee, Nanoleaf and most others; Hue direct is for people
without it. Only the lights listed under a room can ever be touched, and only for a room the guest
is allowed (see "control" in README).

The host's own actions (agent level "plus" or "open") live in data/actions.json. Each is a button
the agent may pick, with typed parameters the code checks, run as a webhook or a Home Assistant
service. Nothing a guest types becomes a URL, a service name or a command.
"""
import json, re, threading, time, urllib.request

_demo = {}            # demo lights: id -> {"on", "brightness"}
_lock = threading.Lock()


def _http(method, url, body=None, headers=None, timeout=6):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data, dict({"content-type": "application/json"}, **(headers or {})), method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw.strip() else {}


# ---------------------------------------------------------------- lights

def light_cfg(h, settings):
    return h.get("lights") or settings.get("lights") or {}


def light_rooms(cfg):
    """{"Bed 3": ["light.a", ...]} with only string ids."""
    return {str(k): [str(x) for x in v if isinstance(x, (str, int))] for k, v in (cfg.get("rooms") or {}).items() if isinstance(v, list)}


def _one(cfg, private, lid):
    kind = cfg.get("kind")
    if kind == "home_assistant":
        st = _http("GET", "%s/api/states/%s" % (cfg["url"].rstrip("/"), lid), headers={"authorization": "Bearer " + private.get("ha_token", "")})
        b = (st.get("attributes") or {}).get("brightness")
        return {"on": st.get("state") == "on", "brightness": round(b / 2.55) if isinstance(b, (int, float)) else None}
    if kind == "hue":
        st = _http("GET", "http://%s/api/%s/lights/%s" % (cfg["bridge"], private.get("hue_user", ""), lid)).get("state") or {}
        b = st.get("bri")
        return {"on": bool(st.get("on")), "brightness": round(b / 2.54) if isinstance(b, (int, float)) else None}
    with _lock:
        return dict(_demo.setdefault(lid, {"on": False, "brightness": 80}))


def lights_state(cfg, private, ids):
    """One room's lights together: on if any is on, brightness of the brightest."""
    if not cfg.get("kind") or not ids:
        return None
    seen = []
    for lid in ids:
        try:
            seen.append(_one(cfg, private, lid))
        except Exception:
            pass
    if not seen:
        return {"ok": False, "on": False, "brightness": None, "count": len(ids)}
    bs = [s["brightness"] for s in seen if s["on"] and s["brightness"] is not None]
    return {"ok": True, "on": any(s["on"] for s in seen), "brightness": max(bs) if bs else None, "count": len(ids)}


def lights_set(cfg, private, ids, on=None, brightness=None):
    """Turn a room's lights on or off, or set brightness 1 to 100 (which also turns them on)."""
    if brightness is not None:
        brightness = max(1, min(int(brightness), 100))
        on = True if on is None else on
    if on is None:
        return {"ok": False, "error": "nothing to change"}
    kind, bad = cfg.get("kind"), 0
    for lid in ids:
        try:
            if kind == "home_assistant":
                svc = "turn_on" if on else "turn_off"
                body = {"entity_id": lid}
                if on and brightness is not None:
                    body["brightness_pct"] = brightness
                _http("POST", "%s/api/services/light/%s" % (cfg["url"].rstrip("/"), svc), body,
                      {"authorization": "Bearer " + private.get("ha_token", "")})
            elif kind == "hue":
                body = {"on": bool(on)}
                if on and brightness is not None:
                    body["bri"] = max(1, round(brightness * 2.54))
                _http("PUT", "http://%s/api/%s/lights/%s/state" % (cfg["bridge"], private.get("hue_user", ""), lid), body)
            else:
                with _lock:
                    s = _demo.setdefault(lid, {"on": False, "brightness": 80})
                    s["on"] = bool(on)
                    if brightness is not None:
                        s["brightness"] = brightness
        except Exception:
            bad += 1
    if bad == len(ids):
        return {"ok": False, "error": "the lights didn't answer"}
    return {"ok": True}


# ---------------------------------------------------------------- pool
#
#     "pool": {"kind": "home_assistant", "url": "http://homeassistant.local:8123",
#              "temp": "sensor.pool_temperature", "heater": "switch.pool_heater"}   (or a climate.* heat pump)
#     "pool": {"kind": "demo"}
#
# Guests see the water temperature. They may switch the heater only when "control": {"pool": "all"}.

_pool_demo = {}       # home id -> {"temp", "heater", "setpoint", "at"}


def pool_cfg(h, settings):
    return h.get("pool") or settings.get("pool") or {}


def _ha(cfg, private, method, path, body=None):
    return _http(method, "%s/api/%s" % (cfg["url"].rstrip("/"), path), body,
                 {"authorization": "Bearer " + private.get("ha_token", "")})


def pool_state(cfg, private, key):
    kind = cfg.get("kind")
    if not kind:
        return None
    label = cfg.get("label") or "Pool"
    try:
        if kind == "home_assistant":
            t = _ha(cfg, private, "GET", "states/" + cfg["temp"]) if cfg.get("temp") else {}
            hv = _ha(cfg, private, "GET", "states/" + cfg["heater"]) if cfg.get("heater") else None
            temp = (t or {}).get("state")
            heater = sp = None
            if hv:
                at = hv.get("attributes") or {}
                heater = hv.get("state") not in ("off", "unavailable", "unknown")
                sp = at.get("temperature")
                if temp in (None, "unknown", "unavailable"):
                    temp = at.get("current_temperature")
            temp = round(float(temp), 1) if temp not in (None, "unknown", "unavailable") else None
            return {"ok": True, "label": label, "temp": temp, "heater": heater, "setpoint": sp, "has_heater": bool(cfg.get("heater"))}
    except Exception:
        return {"ok": False, "label": label, "temp": None, "heater": None, "setpoint": None, "has_heater": bool(cfg.get("heater"))}
    with _lock:   # demo: the water warms toward 30° with the heater on, cools toward 24° with it off
        s = _pool_demo.setdefault(key, {"temp": 26.4, "heater": False, "setpoint": 30, "at": time.time()})
        mins = min(600, time.time() - s["at"]) / 60
        goal = s["setpoint"] if s["heater"] else 24.0
        s["temp"] = round(s["temp"] + (goal - s["temp"]) * min(1, 0.01 * mins), 1)
        s["at"] = time.time()
        return {"ok": True, "label": label, "temp": s["temp"], "heater": s["heater"], "setpoint": s["setpoint"], "has_heater": True, "demo": True}


def pool_set(cfg, private, key, heater):
    if not isinstance(heater, bool):
        return {"ok": False, "error": "nothing to change"}
    try:
        if cfg.get("kind") == "home_assistant":
            ent = cfg.get("heater") or ""
            if ent.startswith("climate."):
                _ha(cfg, private, "POST", "services/climate/set_hvac_mode", {"entity_id": ent, "hvac_mode": "heat" if heater else "off"})
            elif ent:
                _ha(cfg, private, "POST", "services/homeassistant/turn_" + ("on" if heater else "off"), {"entity_id": ent})
            else:
                return {"ok": False, "error": "this pool has no heater set up"}
        else:
            pool_state(cfg, private, key)
            with _lock:
                _pool_demo[key]["heater"] = heater
    except Exception:
        return {"ok": False, "error": "the pool heater didn't answer"}
    return {"ok": True}


# ---------------------------------------------------------------- speakers
#
#     "speakers": {"kind": "home_assistant", "url": "http://homeassistant.local:8123",
#                  "rooms": {"Living": "media_player.living", "Deck": "media_player.deck"}}
#     "speakers": {"kind": "demo", "rooms": {"Living": "living", "Deck": "deck"}}
#
# Home Assistant covers Sonos, Google and Nest speakers, Bose, HEOS and most others. Guests can play,
# pause, skip and set the volume, only in the rooms "control": {"speakers": ...} allows.

_spk_demo = {}        # speaker id -> {"playing", "volume", "track"}
DEMO_TRACKS = ["Saltwater Sunday", "Golden hour on the deck", "Easy morning", "Sunset session"]


def speaker_cfg(h, settings):
    return h.get("speakers") or settings.get("speakers") or {}


def speaker_rooms(cfg):
    return {str(k): str(v) for k, v in (cfg.get("rooms") or {}).items() if isinstance(v, (str, int))}


def speaker_state(cfg, private, sid):
    try:
        if cfg.get("kind") == "home_assistant":
            st = _ha(cfg, private, "GET", "states/" + sid)
            at = st.get("attributes") or {}
            v = at.get("volume_level")
            title = " · ".join(x for x in (at.get("media_title"), at.get("media_artist")) if x)
            return {"ok": True, "playing": st.get("state") == "playing", "volume": round(v * 100) if isinstance(v, (int, float)) else None, "title": title}
    except Exception:
        return {"ok": False, "playing": False, "volume": None, "title": ""}
    with _lock:
        s = _spk_demo.setdefault(sid, {"playing": False, "volume": 30, "track": 0})
        return {"ok": True, "playing": s["playing"], "volume": s["volume"], "title": DEMO_TRACKS[s["track"] % len(DEMO_TRACKS)], "demo": True}


def speaker_set(cfg, private, sid, action, volume=None):
    """action: play, pause, next or volume (0 to 100)."""
    if action not in ("play", "pause", "next", "volume"):
        return {"ok": False, "error": "nothing to change"}
    if action == "volume":
        try:
            volume = max(0, min(int(volume), 100))
        except (TypeError, ValueError):
            return {"ok": False, "error": "volume is 0 to 100"}
    try:
        if cfg.get("kind") == "home_assistant":
            svc, body = {"play": ("media_play", {}), "pause": ("media_pause", {}), "next": ("media_next_track", {}),
                         "volume": ("volume_set", {"volume_level": (volume or 0) / 100})}[action]
            _ha(cfg, private, "POST", "services/media_player/" + svc, dict(body, entity_id=sid))
        else:
            with _lock:
                s = _spk_demo.setdefault(sid, {"playing": False, "volume": 30, "track": 0})
                if action == "play":
                    s["playing"] = True
                elif action == "pause":
                    s["playing"] = False
                elif action == "next":
                    s["track"] += 1
                    s["playing"] = True
                else:
                    s["volume"] = volume
    except Exception:
        return {"ok": False, "error": "the speaker didn't answer"}
    return {"ok": True}


# ---------------------------------------------------------------- the host's own actions

def load_actions(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for a in data.get("actions", []):
        if isinstance(a, dict) and re.fullmatch(r"[a-z0-9_]{1,40}", str(a.get("id", ""))) and isinstance(a.get("run"), dict):
            out.append(a)
    return out


def check_params(action, given):
    """The parameters the host declared, checked. Returns a dict, or None when something is wrong."""
    given = given if isinstance(given, dict) else {}
    out = {}
    for name, spec in (action.get("params") or {}).items():
        v, t = given.get(name), spec.get("type", "text")
        if v is None:
            if spec.get("required", True):
                return None
            continue
        if t == "int":
            try:
                v = int(v)
            except (TypeError, ValueError):
                return None
            if not (spec.get("min", -10**9) <= v <= spec.get("max", 10**9)):
                return None
        elif t == "choice":
            if v not in spec.get("options", []):
                return None
        else:
            v = re.sub(r"[^\w .,:'@+/-]", "", str(v))[: int(spec.get("max_chars", 60))].strip()
            if not v:
                return None
        out[name] = v
    return out


def run_action(action, params, private):
    r = action["run"]
    try:
        if r.get("webhook"):
            _http(r.get("method", "POST").upper(), r["webhook"], {"action": action["id"], "params": params},
                  {k: str(v) for k, v in (r.get("headers") or {}).items()}, timeout=15)
        elif r.get("home_assistant"):
            svc = r["home_assistant"]   # "script.turn_on"
            if not re.fullmatch(r"[a-z_]+\.[a-z_]+", svc):
                return {"ok": False, "error": "bad service"}
            body = dict(r.get("data") or {}, **({"variables": params} if params else {}))
            _http("POST", "%s/api/services/%s" % (r["url"].rstrip("/"), svc.replace(".", "/")), body,
                  {"authorization": "Bearer " + private.get("ha_token", "")}, timeout=15)
        else:
            return {"ok": False, "error": "no way to run it"}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}
    return {"ok": True}
