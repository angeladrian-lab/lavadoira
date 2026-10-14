"""Dashboard local: http://<ip-del-mac>:8765  (accesible desde la red de casa; sin contraseña).

Uso:  .venv/bin/python dashboard.py [puerto]
Lee history.db (lo llenan monitor_local.py, import_xls.py y backfill.py).
"""
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import analysis
import store

HERE = Path(__file__).parent
NAMES = ("lavadora", "secadora")
TYPICAL_WINDOW = 90 * 86400  # los ciclos de los últimos 90 días definen la duración "habitual"


def build(days):
    now = int(time.time())
    since = 0 if days == 0 else now - days * 86400
    out = {"now": now, "days": days, "appliances": {}, "series": {}, "cycles": [], "daily": {}, "hours": {}, "stats": {}}
    daily = defaultdict(lambda: {n: {"n": 0, "wh": 0.0} for n in NAMES})

    for name in NAMES:
        cfg = analysis.CFG[name]
        readings = store.fetch(name, 0)
        cycles = analysis.detect_cycles(readings, cfg)
        recent_done = [c for c in cycles if not c["ongoing"] and c["start"] >= now - TYPICAL_WINDOW]
        typical = analysis.typical_duration(recent_done)
        out["appliances"][name] = analysis.live_status(readings, cycles, typical, now)
        out["appliances"][name]["typical"] = typical

        shown = [c for c in cycles if c["end"] >= since]
        out["series"][name] = analysis.downsample([r for r in readings if r[0] >= since])
        for c in shown:
            out["cycles"].append({**c, "appliance": name})
            d = daily[datetime.fromtimestamp(c["start"]).strftime("%Y-%m-%d")][name]
            d["n"] += 1
            d["wh"] += c["wh"]
        hours = [0] * 24
        for c in shown:
            hours[datetime.fromtimestamp(c["start"]).hour] += 1
        out["hours"][name] = hours

        finished = [c for c in shown if not c["ongoing"]]
        out["stats"][name] = {
            "cycles": len(shown),
            "run_seconds": sum(c["duration"] for c in shown),
            "kwh": round(sum(c["wh"] for c in shown) / 1000, 2),
            "avg_duration": round(sum(c["duration"] for c in finished) / len(finished)) if finished else None,
            "has_data": bool(readings),
        }

    out["cycles"].sort(key=lambda c: c["start"], reverse=True)
    out["daily"] = [{"date": d, **{n: {"n": v[n]["n"], "wh": round(v[n]["wh"])} for n in NAMES}}
                    for d, v in sorted(daily.items())]
    return out


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/data":
            try:
                days = int(parse_qs(url.query).get("days", ["7"])[0])
                self._send(200, json.dumps(build(max(days, 0))).encode(), "application/json")
            except Exception as e:  # el dashboard no debe caerse por una petición mala
                self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")
        elif url.path in ("/", "/index.html"):
            self._send(200, (HERE / "dashboard.html").read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(404, b"no encontrado", "text/plain; charset=utf-8")

    def log_message(self, *args):  # sin ruido en la terminal
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"Dashboard en http://127.0.0.1:{port} y en la red local (Ctrl+C para parar)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
