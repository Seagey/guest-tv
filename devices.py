"""Smart lights and the host's own actions, for the Guest remote and the guest agent.

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
