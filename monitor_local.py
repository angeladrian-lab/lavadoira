"""Versión local: lee los P110 por la wifi de casa, avisa por WhatsApp (CallMeBot) y sirve el dashboard.

Se queda en marcha y consulta cada POLL_SECONDS. Configuración en .env (no se sube a git):
  TAPO_EMAIL, TAPO_PASSWORD, WHATSAPP_RECIPIENTS   (opcional: WASHER_ALIAS, DRYER_ALIAS, DASHBOARD_PORT, TAPO_IPS)
Los enchufes se buscan solos en la red local en cada arranque (y cuando dejan de responder), y se asignan a
lavadora/secadora por su nombre en la app Tapo: no hace falta fijar IP en el router. TAPO_IPS es solo una pista.
Todos los WhatsApp llevan el enlace al dashboard, que este mismo proceso sirve en la red local.
"""
import asyncio
import json
import os
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import netscan
import store
from monitor import APPLIANCES, send_whatsapp, step

HERE = Path(__file__).parent
STATE_FILE = HERE / "state_local.json"
POLL_SECONDS = 30
RETRY_DISCOVERY_SECONDS = 60
PROBE_TIMEOUT = 10


def load_env():
    f = HERE / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def dashboard_url():
    return f"http://{netscan.local_ip()}:{os.environ.get('DASHBOARD_PORT', '8765')}"


def notify(text):
    return send_whatsapp(text, link=dashboard_url())


def start_dashboard():
    from dashboard import Handler

    port = int(os.environ.get("DASHBOARD_PORT", "8765"))
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    except OSError as e:
        print(f"Dashboard no iniciado en el puerto {port}: {e}", flush=True)
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Dashboard en {dashboard_url()}", flush=True)


async def probe(client, ip):
    """Devuelve (handler, nickname) si la IP es un P110 de esta cuenta; si no, None."""
    try:
        dev = await asyncio.wait_for(client.p110(ip), PROBE_TIMEOUT)
        info = await asyncio.wait_for(dev.get_device_info(), PROBE_TIMEOUT)
        return dev, info.nickname.strip().lower(), ip
    except Exception:  # router, extensor u otro aparato: se ignora
        return None


async def discover(client, wanted, hints):
    """Busca los enchufes: primero las IP conocidas y, si falta alguno, barre la red. Devuelve {clave: (handler, ip)}."""
    found, tried = {}, set()

    async def try_ips(ips):
        ips = [i for i in ips if i not in tried]
        tried.update(ips)
        for res in await asyncio.gather(*(probe(client, ip) for ip in ips)):
            if res:
                dev, nick, ip = res
                for key, alias in wanted.items():
                    if nick == alias:
                        found[key] = (dev, ip)

    await try_ips(hints)
    for attempt in range(3):
        if len(found) == len(wanted):
            break
        await try_ips(await netscan.scan())
        await asyncio.sleep(2)
    return found


async def main():
    from tapo import ApiClient

    load_env()
    start_dashboard()
    wanted = {k: os.environ.get(c["alias_env"], k).strip().lower() for k, c in APPLIANCES.items()}
    client = ApiClient(os.environ["TAPO_EMAIL"], os.environ["TAPO_PASSWORD"])
    states = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    hints = [i.strip() for i in os.environ.get("TAPO_IPS", "").split(",") if i.strip()]
    hints += [s["ip"] for s in states.values() if isinstance(s, dict) and s.get("ip")]

    devices = await discover(client, wanted, hints)
    for key, (_, ip) in devices.items():
        print(f"{key}: {ip}", flush=True)
    miss = sorted(set(wanted) - set(devices))
    arranque = "Monitor de lavadora y secadora arrancado." + (
        f" ⚠️ No encuentro: {', '.join(miss)}." if miss else "")
    print("Aviso de arranque enviado" if notify(arranque) else "Aviso de arranque NO enviado", flush=True)

    last_discovery = time.time()
    while True:
        if len(devices) < len(wanted) and time.time() - last_discovery > RETRY_DISCOVERY_SECONDS:
            devices = {**devices, **await discover(client, {k: v for k, v in wanted.items() if k not in devices}, [])}
            last_discovery = time.time()
        readings = {}
        for key, cfg in APPLIANCES.items():
            if key not in devices:
                continue
            dev, ip = devices[key]
            try:
                watts = (await dev.get_current_power()).current_power
            except Exception as e:  # sin respuesta: la IP pudo cambiar, se vuelve a buscar
                print(f"{key}: sin lectura en {ip} ({type(e).__name__}); busco de nuevo", flush=True)
                del devices[key]
                last_discovery = 0
                continue
            readings[key] = watts
            store.add_many([(key, int(time.time()), watts)])  # histórico para el dashboard
            new, event = step(states.get(key), watts, time.time(), cfg)
            new = {**new, "ip": ip}
            if event:
                text = f"{cfg['label']} ha {'empezado' if event == 'started' else 'terminado'}"
                print(f"{key}: {watts:.1f} W -> {text}", flush=True)
                if not notify(text):
                    continue  # no se pudo avisar: se reintenta en la siguiente vuelta
            if new != states.get(key):
                states[key] = new
                STATE_FILE.write_text(json.dumps(states, indent=2) + "\n")
        if readings:
            print(time.strftime("%H:%M:%S"), " · ".join(f"{k} {w:.0f} W" for k, w in readings.items()), flush=True)
        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
