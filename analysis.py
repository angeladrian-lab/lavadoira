"""Detección de ciclos y estimación del tiempo restante a partir del histórico."""
import statistics

# Mismos umbrales que el monitor (una sola fuente de verdad: monitor.APPLIANCES).
from monitor import APPLIANCES

CFG = {k: {x: v[x] for x in ("start_w", "idle_w", "idle_min")} for k, v in APPLIANCES.items()}
MAX_GAP = 15 * 60  # más de 15 min sin lecturas = hueco de datos: el ciclo se corta ahí
STALE = 5 * 60  # sin lecturas desde hace más de esto = no sabemos si sigue en marcha


def detect_cycles(readings, cfg):
    """readings: [(ts, watts)] ordenadas. Devuelve lista de ciclos; el último puede tener ongoing=True."""
    cycles, cur = [], None

    def close(c, end_ts):
        c["end"] = end_ts
        c["duration"] = max(end_ts - c["start"], 0)
        c["ongoing"] = False
        cycles.append(c)

    prev_ts = prev_w = None
    for ts, w in readings:
        if cur is not None:
            if ts - prev_ts > MAX_GAP:
                close(cur, cur["last_active"])
                cur = None
            else:
                cur["wh"] += (ts - prev_ts) * (w + prev_w) / 2 / 3600
                if w > cfg["idle_w"]:
                    cur["last_active"] = ts
                    cur["peak"] = max(cur["peak"], w)
                elif ts - cur["last_active"] >= cfg["idle_min"] * 60:
                    close(cur, cur["last_active"])
                    cur = None
        if cur is None and w > cfg["start_w"]:
            cur = {"start": ts, "last_active": ts, "peak": w, "wh": 0.0}
        prev_ts, prev_w = ts, w

    if cur is not None:
        cur.update(end=cur["last_active"], duration=cur["last_active"] - cur["start"], ongoing=True)
        cycles.append(cur)
    for c in cycles:
        c["wh"] = round(c["wh"], 1)
        c["peak"] = round(c["peak"])
        c.pop("last_active", None)
    return cycles


def typical_duration(done_cycles):
    """Mediana y rango intercuartílico de la duración de ciclos terminados (descarta ciclos de < 5 min)."""
    durs = sorted(c["duration"] for c in done_cycles if c["duration"] >= 300)
    if len(durs) < 2:
        return None
    q = statistics.quantiles(durs, n=4) if len(durs) >= 4 else [durs[0], statistics.median(durs), durs[-1]]
    return {"median": statistics.median(durs), "p25": q[0], "p75": q[2], "n": len(durs)}


def live_status(readings, cycles, typical, now):
    """Estado actual: parada / en marcha (con progreso y tiempo restante estimado) / sin datos recientes."""
    if not readings:
        return {"status": "nodata"}
    last_ts, last_w = readings[-1]
    age = now - last_ts
    out = {"current_w": round(last_w, 1), "last_reading_age": age}
    last = cycles[-1] if cycles else None
    done = [c for c in cycles if not c["ongoing"]]
    if done:
        out["last_cycle"] = {"end": done[-1]["end"], "duration": done[-1]["duration"]}
    if age > STALE:
        out["status"] = "offline"
        return out
    if last and last["ongoing"]:
        elapsed = now - last["start"]
        out.update(status="running", cycle_start=last["start"], elapsed=elapsed)
        if typical:
            expected = typical["median"]
            over = elapsed > expected
            out["expected"] = expected
            out["range"] = [typical["p25"], typical["p75"]]
            out["over"] = over
            # nunca marca 100 % mientras siga en marcha: el tope es 97 %
            out["progress"] = min(elapsed / expected, 0.97)
            out["remaining"] = None if over else max(expected - elapsed, 0)
    else:
        out["status"] = "idle"
    return out


def downsample(readings, max_points=1200):
    """Reduce la serie conservando los picos (máximo por cubo)."""
    if len(readings) <= max_points:
        return [[ts, w] for ts, w in readings]
    size = -(-len(readings) // max_points)
    out = []
    for i in range(0, len(readings), size):
        chunk = readings[i:i + size]
        peak = max(chunk, key=lambda r: r[1])
        out.append([chunk[len(chunk) // 2][0], peak[1]])
    return out
