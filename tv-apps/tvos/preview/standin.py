"""A stand-in house computer for drawing Guest TV without an Apple TV (for developers).

    .venv/bin/python tv-apps/tvos/preview/standin.py [port]

Answers GET /api/tv/native the way server.py's native_screen does, with made up stay details, a home photo
from web/homes and real QR codes (segno), on 127.0.0.1 only. Two homes: "lake" (a guest staying: Wi-Fi,
the Guest remote, door codes) and "plain" (between stays: no Wi-Fi, house info). render.sh draws both.
"""
import io, json, os, sys, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import segno

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def screen(home, base):
    q = "home=" + home
    if home == "plain":
        return {"home": home, "mode": "airbnb", "phase": "between", "active": False, "eyebrow": "Holiday home",
                "title": "Welcome to Lakeside", "sub": "Your stay details show here when you arrive.", "welcome": "",
                "photo": base + "/tv/homes/ridge-hero.jpg", "wifi": None, "wifi_qr": None,
                "remote_qr": "%s/api/qr?%s&what=phone&fmt=png" % (base, q), "remote_label": "House info", "access": [],
                "weather": {"place": "Byron Bay", "temp": 19, "code": 3, "hi": 22, "lo": 13, "rain": 0},
                "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
    return {"home": home, "mode": "airbnb", "phase": "during", "active": True, "eyebrow": "Lakeside",
            "title": "Good morning, Sarah and Tom", "sub": "Sun 1 Nov to Wed 4 Nov · Night 2 of 3",
            "welcome": "Firewood is by the back door, and the kayaks are yours to use.",
            "photo": base + "/tv/homes/lake-hero.jpg",
            "wifi": {"ssid": "Lakeside Guest", "password": "still-water-24"},
            "wifi_qr": "%s/api/qr?%s&what=wifi&fmt=png" % (base, q),
            "remote_qr": "%s/api/qr?%s&what=remote&fmt=png" % (base, q), "remote_label": "Guest remote",
            "access": [{"label": "Front door", "code": "4821"}, {"label": "Gate", "code": "1907"}],
            "weather": {"place": "Byron Bay", "temp": 26, "code": 1, "hi": 28, "lo": 17, "rain": 40},
            "time": time.strftime("%Y-%m-%dT%H:%M:%S")}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = dict(urllib.parse.parse_qsl(u.query))
        base = "http://" + self.headers.get("Host")
        if u.path == "/api/tv/native":
            return self.send(200, json.dumps(screen(qs.get("home", "lake"), base)).encode(), "application/json")
        if u.path == "/api/qr":
            text = {"wifi": "WIFI:T:WPA;S:Lakeside Guest;P:still-water-24;;"}.get(qs.get("what"), "http://example.com/r/")
            buf = io.BytesIO()
            segno.make(text, error="m").save(buf, kind="png", scale=8, border=2)
            return self.send(200, buf.getvalue(), "image/png")
        if u.path.startswith("/tv/homes/"):
            f = os.path.join(ROOT, "web", "homes", os.path.basename(u.path))
            if os.path.isfile(f):
                return self.send(200, open(f, "rb").read(), "image/jpeg")
        self.send(404, b"{}", "application/json")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5419
    print("stand-in house computer on http://127.0.0.1:%d" % port, flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
