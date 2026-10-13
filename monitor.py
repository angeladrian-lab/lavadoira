"""Avisa por WhatsApp (CallMeBot) cuando la lavadora/secadora (enchufes Tapo P110) empiezan y terminan.

Se ejecuta cada pocos minutos desde GitHub Actions. El estado se guarda en state.json.
Uso:  python monitor.py            -> ciclo normal
      python monitor.py --diagnose -> lista dispositivos y muestra la lectura cruda (no envía nada)
"""
import asyncio
import base64
import binascii
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

STATE_FILE = Path(__file__).with_name("state.json")

# Umbrales deducidos de los Excel (potencia en W, standby 0-2 W, ciclo con picos de 1800-2200 W).
# start_w: por encima de esto se considera "en marcha". idle_w: por debajo (o igual) se considera "parado".
# idle_min: minutos seguidos parado para dar el ciclo por terminado.
APPLIANCES = {
    "lavadora": {"label": "La lavadora", "alias_env": "WASHER_ALIAS", "start_w": 10, "idle_w": 3, "idle_min": 10},
    "secadora": {"label": "La secadora", "alias_env": "DRYER_ALIAS", "start_w": 50, "idle_w": 3, "idle_min": 10},
}


def step(state, power_w, now, cfg):
    """Máquina de estados pura. Devuelve (nuevo_estado, evento) con evento in {None,'started','finished'}."""
    state = dict(state or {})
    running = state.get("running", False)
    idle_since = state.get("idle_since")
    event = None

    if not running:
        if power_w > cfg["start_w"]:
            state.update(running=True, idle_since=None)
            event = "started"
    else:
        if power_w > cfg["idle_w"]:
            state["idle_since"] = None
        else:
            if idle_since is None:
                state["idle_since"] = now
            elif now - idle_since >= cfg["idle_min"] * 60:
                state.update(running=False, idle_since=None)
                event = "finished"
    return state, event


# ---------- Nube Tapo ----------

def _decode_alias(alias):
    try:
        return base64.b64decode(alias, validate=True).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return alias or ""


async def read_powers(wanted):
    """wanted: {clave: alias}. Devuelve {clave: vatios}."""
    from tplinkcloud.client import TPLinkApi
    from tplinkcloud.device_client import TPLinkDeviceClient
    from tplinkcloud.device_info import TPLinkDeviceInfo

    term_id = os.environ.get("TAPO_TERM_ID", "6b1f3c0e-5d0e-4c53-9a77-1d2f4a0b7c11")
    api = TPLinkApi(cloud_type="tapo", term_id=term_id)
    login = api.login(os.environ["TAPO_EMAIL"], os.environ["TAPO_PASSWORD"])
    token = login["token"]
    infos = [TPLinkDeviceInfo(d, cloud_type="tapo") for d in api.get_device_info_list(token)]
    by_alias = {_decode_alias(i.alias).strip().lower(): i for i in infos}

    out = {}
    for key, alias in wanted.items():
        info = by_alias.get(alias.strip().lower())
        if info is None:
            raise SystemExit(f"No encuentro el dispositivo '{alias}'. Disponibles: {sorted(by_alias)}")
        client = TPLinkDeviceClient(
            info.app_server_url, token, term_id=term_id,
            access_key=api.access_key, secret_key=api.secret_key,
            app_name=api._app_name, cloud_type="tapo",
        )
        out[key] = await _current_power(client, info.device_id)
    return out


async def _current_power(client, device_id):
    resp = await client.pass_through_request(device_id, {"method": "get_energy_usage"})
    result = (resp or {}).get("result") or {}
    if "current_power" in result:
        return result["current_power"] / 1000.0  # get_energy_usage da mW
    resp = await client.pass_through_request(device_id, {"method": "get_current_power"})
    result = (resp or {}).get("result") or {}
    if "current_power" in result:
        return float(result["current_power"])  # W
    raise RuntimeError(f"Respuesta sin potencia del dispositivo {device_id}: {resp}")


async def diagnose():
    from tplinkcloud.client import TPLinkApi
    from tplinkcloud.device_client import TPLinkDeviceClient
    from tplinkcloud.device_info import TPLinkDeviceInfo

    term_id = os.environ.get("TAPO_TERM_ID", "6b1f3c0e-5d0e-4c53-9a77-1d2f4a0b7c11")
    api = TPLinkApi(cloud_type="tapo", term_id=term_id)
    token = api.login(os.environ["TAPO_EMAIL"], os.environ["TAPO_PASSWORD"])["token"]
    # Los logs de Actions son públicos: solo se imprimen códigos de error y nombres de campos, nunca valores de dispositivo.
    wanted = {os.environ.get(c["alias_env"], k).strip().lower() for k, c in APPLIANCES.items()}
    for d in api.get_device_info_list(token):
        i = TPLinkDeviceInfo(d, cloud_type="tapo")
        if _decode_alias(i.alias).strip().lower() not in wanted:
            continue
        print(f"- dispositivo configurado encontrado, modelo={i.device_model}")
        client = TPLinkDeviceClient(
            i.app_server_url, token, term_id=term_id, access_key=api.access_key,
            secret_key=api.secret_key, app_name=api._app_name, cloud_type="tapo",
        )
        variants = {
            "get_device_info": {"method": "get_device_info"},
            "handshake": {"method": "handshake", "params": {"key": "x"}},
            "get_energy_usage": {"method": "get_energy_usage"},
            "get_current_power": {"method": "get_current_power"},
            "multipleRequest": {"method": "multipleRequest",
                                "params": {"requests": [{"method": "get_energy_usage"}]}},
        }
        for name, rd in variants.items():
            try:
                raw = await client._request_post(
                    {"deviceId": i.device_id, "requestData": json.dumps(rd)},
                    url_path="/api/v2/common/passthrough")
                body = raw._response
                inner = body.get("result", {}).get("responseData") if isinstance(body.get("result"), dict) else None
                if isinstance(inner, str):
                    try:
                        inner = json.loads(inner)
                    except ValueError:
                        inner = None
                print(f"    {name}: error_code={body.get('error_code')} msg={body.get('msg')} "
                      f"campos_respuesta={sorted(inner) if isinstance(inner, dict) else None}")
            except Exception as e:
                print(f"    {name}: ERROR {type(e).__name__}")


# ---------- WhatsApp (CallMeBot) ----------

def send_whatsapp(text):
    """WHATSAPP_RECIPIENTS = 'telefono1:apikey1,telefono2:apikey2' (telefono con prefijo, p. ej. 34600111222)."""
    failures = []
    for pair in os.environ["WHATSAPP_RECIPIENTS"].split(","):
        phone, key = pair.strip().split(":")
        url = "https://api.callmebot.com/whatsapp.php?" + urllib.parse.urlencode(
            {"phone": phone, "text": text, "apikey": key})
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                if r.status != 200:
                    failures.append(f"{phone}: HTTP {r.status}")
        except Exception as e:
            failures.append(f"{phone}: {e}")
    if failures:
        print("Fallos enviando WhatsApp:", failures, file=sys.stderr)
    return not failures


# ---------- Main ----------

def main():
    if "--diagnose" in sys.argv:
        asyncio.run(diagnose())
        return

    wanted = {k: os.environ.get(c["alias_env"], k.capitalize()) for k, c in APPLIANCES.items()}
    powers = asyncio.run(read_powers(wanted))

    states = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    now = time.time()
    new_states = dict(states)
    for key, cfg in APPLIANCES.items():
        new, event = step(states.get(key), powers[key], now, cfg)
        print(f"{key}: {powers[key]:.1f} W estado={new} evento={event}")
        if event:
            text = f"{cfg['label']} ha {'empezado' if event == 'started' else 'terminado'}"
            if not send_whatsapp(text):
                # no consumir el evento si no se pudo avisar: se reintentará en la próxima ejecución
                new = states.get(key) or {}
        new_states[key] = new
    if new_states != states:
        STATE_FILE.write_text(json.dumps(new_states, indent=2) + "\n")


if __name__ == "__main__":
    main()
