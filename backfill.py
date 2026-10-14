"""Recupera del propio enchufe el histórico de potencia (cada 5 min) y lo guarda en history.db.

Uso:  .venv/bin/python backfill.py [dias]     (por defecto 7; el enchufe guarda un tiempo limitado)
Necesita el .env con TAPO_EMAIL, TAPO_PASSWORD y TAPO_IPS. Se puede repetir sin duplicar.
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timedelta

import store
from monitor_local import connect, load_env
from monitor import APPLIANCES


async def main(days):
    from tapo import ApiClient
    from tapo.requests import PowerDataInterval

    load_env()
    ips = [i.strip() for i in os.environ["TAPO_IPS"].split(",") if i.strip()]
    wanted = {k: os.environ.get(c["alias_env"], k).strip().lower() for k, c in APPLIANCES.items()}
    devices = await connect(ApiClient(os.environ["TAPO_EMAIL"], os.environ["TAPO_PASSWORD"]), ips, wanted)
    end = datetime.now()
    for key, dev in devices.items():
        total = 0
        day = end - timedelta(days=days)
        while day < end:  # trozos de 1 día para no pedir más de lo que admite el enchufe
            chunk_end = min(day + timedelta(days=1), end)
            try:
                res = await dev.get_power_data(PowerDataInterval.Every5Minutes, day, chunk_end)
                t0 = res.start_date_time
                step_s = res.interval_length * 60
                base = int(time.mktime(t0.timetuple()))
                rows = [(key, base + i * step_s, float(w)) for i, w in enumerate(res.entries) if w is not None]
                total += store.add_many(rows)
            except Exception as e:
                print(f"  {key} {day:%d/%m}: {type(e).__name__}: {e}")
            day = chunk_end
        print(f"{key}: {total} lecturas nuevas")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 7))
