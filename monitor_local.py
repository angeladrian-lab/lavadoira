"""Versión local: lee los P110 directamente por la wifi de casa y avisa por WhatsApp (CallMeBot).

Se queda en marcha y consulta cada POLL_SECONDS. Configuración en .env (no se sube a git):
  TAPO_EMAIL, TAPO_PASSWORD, WHATSAPP_RECIPIENTS, TAPO_IPS=ip1,ip2   (opcional: WASHER_ALIAS, DRYER_ALIAS)
Los enchufes se asignan a lavadora/secadora por su nombre en la app Tapo.
"""
import asyncio
import json
import os
import time
from pathlib import Path

from monitor import APPLIANCES, send_whatsapp, step

HERE = Path(__file__).parent
STATE_FILE = HERE / "state_local.json"
POLL_SECONDS = 30


def load_env():
    f = HERE / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


async def connect(client, ips, wanted):
    """Devuelve {clave: handler} asignando cada IP por el nombre del enchufe."""
    out = {}
    for ip in ips:
        dev = await client.p110(ip)
        nick = (await dev.get_device_info()).nickname.strip().lower()
        for key, alias in wanted.items():
            if nick == alias:
                out[key] = dev
                print(f"{key}: {ip} ('{nick}')", flush=True)
    missing = set(wanted) - set(out)
    if missing:
        raise SystemExit(f"No he encontrado enchufes con el nombre de: {sorted(missing)} en {ips}")
    return out


async def main():
    from tapo import ApiClient

    load_env()
    ips = [i.strip() for i in os.environ["TAPO_IPS"].split(",") if i.strip()]
    wanted = {k: os.environ.get(c["alias_env"], k).strip().lower() for k, c in APPLIANCES.items()}
    client = ApiClient(os.environ["TAPO_EMAIL"], os.environ["TAPO_PASSWORD"])
    devices = await connect(client, ips, wanted)
    states = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}

    while True:
        for key, cfg in APPLIANCES.items():
            try:
                watts = (await devices[key].get_current_power()).current_power
            except Exception as e:  # enchufe sin respuesta: se salta este ciclo sin tocar el estado
                print(f"{key}: sin lectura ({type(e).__name__})", flush=True)
                try:
                    devices = await connect(client, ips, wanted)
                except BaseException as e2:
                    print(f"  reconexión fallida: {e2}", flush=True)
                continue
            new, event = step(states.get(key), watts, time.time(), cfg)
            if event:
                text = f"{cfg['label']} ha {'empezado' if event == 'started' else 'terminado'}"
                print(f"{key}: {watts:.1f} W -> {text}", flush=True)
                if not send_whatsapp(text):
                    continue  # no se pudo avisar: se reintenta en la siguiente vuelta
            if new != states.get(key):
                states[key] = new
                STATE_FILE.write_text(json.dumps(states, indent=2) + "\n")
        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
