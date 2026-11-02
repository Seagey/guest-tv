"""Test lights, host actions and the code checks, with no real devices and no Claude.
A fake Home Assistant and a fake Hue bridge run on this computer for the test.

    .venv/bin/python tools/devices_test.py
"""
import json, os, sys, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import devices, guest_agent

HA = {"light.bed": {"state": "off", "attributes": {}}, "light.lamp": {"state": "on", "attributes": {"brightness": 128}}}
HUE = {"4": {"on": False, "bri": 100}}
CALLS = []


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, body):
        b = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        n = int(self.headers.get("content-length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        p = self.path.split("/")
        if self.path.startswith("/api/states/"):
            assert self.headers.get("authorization") == "Bearer t0ken"
            return self.reply(HA[p[3]])
        if self.path.startswith("/api/hueuser/lights/"):
            return self.reply({"state": HUE[p[4]]})
        self.reply({})

    def do_POST(self):
        b = self.body()
        CALLS.append((self.path, b))
        if self.path.startswith("/api/services/light/"):
            e = HA[b["entity_id"]]
            e["state"] = "on" if self.path.endswith("turn_on") else "off"
            if "brightness_pct" in b:
                e["attributes"]["brightness"] = round(b["brightness_pct"] * 2.55)
        self.reply([])

    def do_PUT(self):
        b = self.body()
        HUE[self.path.split("/")[4]].update(b)
        self.reply([{"success": {}}])


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d" % srv.server_port
PV = {"ha_token": "t0ken", "hue_user": "hueuser"}
ok = bad = 0


def t(name, cond):
    global ok, bad
    ok, bad = ok + bool(cond), bad + (not cond)
    print(("PASS " if cond else "FAIL ") + name)


# lights: Home Assistant
ha = {"kind": "home_assistant", "url": URL, "rooms": {"Bed 3": ["light.bed", "light.lamp"]}}
s = devices.lights_state(ha, PV, ["light.bed", "light.lamp"])
t("HA reads: on because one is on, brightness 50", s["on"] and s["brightness"] == 50)
devices.lights_set(ha, PV, ["light.bed", "light.lamp"], on=False)
t("HA turns both off", not devices.lights_state(ha, PV, ["light.bed", "light.lamp"])["on"])
devices.lights_set(ha, PV, ["light.bed"], brightness=30)
t("HA brightness 30 turns it on at 30", HA["light.bed"]["state"] == "on" and devices.lights_state(ha, PV, ["light.bed"])["brightness"] == 30)

# lights: Hue
hue = {"kind": "hue", "bridge": "127.0.0.1:%d" % srv.server_port, "rooms": {"Bed 3": ["4"]}}
devices.lights_set(hue, PV, ["4"], on=True, brightness=100)
t("Hue on at 100", HUE["4"]["on"] and HUE["4"]["bri"] == 254)
t("Hue reads back", devices.lights_state(hue, PV, ["4"])["brightness"] == 100)

# lights: demo
demo = {"kind": "demo"}
devices.lights_set(demo, PV, ["x"], on=True, brightness=40)
t("demo lights", devices.lights_state(demo, PV, ["x"]) == {"ok": True, "on": True, "brightness": 40, "count": 1})

# host actions
act = {"id": "pool_heat", "label": "Pool heater", "params": {"hours": {"type": "int", "min": 1, "max": 4}, "mode": {"type": "choice", "options": ["eco", "fast"]}},
       "run": {"webhook": URL + "/hook"}}
t("params in range pass", devices.check_params(act, {"hours": 2, "mode": "eco"}) == {"hours": 2, "mode": "eco"})
t("params out of range fail", devices.check_params(act, {"hours": 9, "mode": "eco"}) is None)
t("unknown choice fails", devices.check_params(act, {"hours": 2, "mode": "$(rm -rf)"}) is None)
devices.run_action(act, {"hours": 2, "mode": "eco"}, PV)
t("webhook gets only the checked params", CALLS[-1] == ("/hook", {"action": "pool_heat", "params": {"hours": 2, "mode": "eco"}}))
t("bad action ids are dropped", devices.load_actions("/nonexistent") == [])

# the agent's code checks, no Claude
rooms = [{"id": "Bed 3", "label": "Your room", "aircon": {"zone": 3, "on": False, "setpoint": 22, "min": 18, "max": 28}, "lights": {"on": False}},
         {"id": "Lounge", "label": "Lounge", "aircon": None, "lights": {"on": True}}]
places = [{"name": "Pixie Food & Wine", "book": "https://example.com/book", "category": "Eat"}]
base = {"apps": [], "rooms": rooms, "places": places, "level": "locked", "actions": [act]}
_, a = guest_agent.check({"actions": [{"do": "lights", "room": "Lounge", "on": False}, {"do": "lights", "room": "Master", "on": False}]}, base)
t("lights only for listed rooms", [x["room"] for x in a] == ["Lounge"])
_, a = guest_agent.check({"actions": [{"do": "aircon", "room": "Lounge", "setpoint": 20}]}, base)
t("aircon only where there is aircon", a == [])
_, a = guest_agent.check({"actions": [{"do": "aircon", "room": "your room", "setpoint": 12}]}, base)
t("aircon out of range is dropped", a == [])
_, a = guest_agent.check({"actions": [{"do": "place", "name": "Pixie Food & Wine"}, {"do": "place", "name": "Evil https://x.y"}]}, base)
t("Book a table only for guide places", a == [{"do": "place", "name": "Pixie Food & Wine"}])
_, a = guest_agent.check({"actions": [{"do": "action", "id": "pool_heat", "params": {"hours": 2, "mode": "eco"}}]}, base)
t("host actions ignored when locked", a == [])
_, a = guest_agent.check({"actions": [{"do": "action", "id": "pool_heat", "params": {"hours": 2, "mode": "eco"}}]}, dict(base, level="plus"))
t("host actions allowed on plus", len(a) == 1)
_, a = guest_agent.check({"actions": [{"do": "book", "place": "Pixie Food & Wine", "people": 2, "when": "Sat 7pm"}]}, dict(base, level="plus"))
t("no booking unless open with booking set up", a == [])
_, a = guest_agent.check({"actions": [{"do": "book", "place": "Pixie Food & Wine", "people": 99, "when": "Sat 7pm; rm -rf"}]},
                         dict(base, level="open", booking={"mcp_file": "x"}))
t("booking checked: place from guide, people capped, text cleaned", a and a[0]["people"] == 20 and ";" not in a[0]["when"])
tok = guest_agent._offer("book", {"place": "Pixie Food & Wine"}, "code-a")
t("a card only confirms from the remote it was offered to", guest_agent.confirm({"token": tok}, base, "code-b")["ok"] is False)
p = guest_agent.prompt_parts(dict(base, level="open", booking={"mcp_file": "x"}, open={"web": True}))
t("prompt lists both rooms and the book action", "Lounge" in p["rooms"] and '"do": "book"' in p["menu"] and "{{" not in p["menu"])
p = guest_agent.prompt_parts(dict(base, rooms=[]))
t("no rooms: no aircon or lights in the menu", '"aircon"' not in p["menu"] and '"lights"' not in p["menu"])

print("\n%d passed, %d failed" % (ok, bad))
sys.exit(1 if bad else 0)
