"""Importa los Excel exportados de la app Tapo (hoja 'Día', datos cada 5 min) al histórico.

Uso:  .venv/bin/python import_xls.py [Potencia-lavadora.xls Potencia-secadora.xls ...]
El nombre del fichero decide la máquina (debe contener 'lavadora' o 'secadora'). Se puede repetir sin duplicar.
"""
import sys
import time
from datetime import datetime
from pathlib import Path

import xlrd

import store

HERE = Path(__file__).parent


def read_sheet(path, sheet="Día"):
    book = xlrd.open_workbook(path)
    ws = book.sheet_by_name(sheet)
    for r in range(1, ws.nrows):  # la fila 0 es cabecera
        stamp, watts = ws.cell_value(r, 0), ws.cell_value(r, 1)
        if stamp == "" or watts == "":
            continue
        t = datetime.strptime(str(stamp), "%Y/%m/%d %H:%M:%S")  # hora local
        yield int(time.mktime(t.timetuple())), float(watts)


def main(paths):
    paths = paths or sorted(HERE.glob("Potencia-*.xls"))
    for p in paths:
        p = Path(p)
        name = next((k for k in ("lavadora", "secadora") if k in p.name.lower()), None)
        if not name:
            print(f"Salto {p.name}: no contiene 'lavadora' ni 'secadora'")
            continue
        rows = [(name, ts, w) for ts, w in read_sheet(p)]
        print(f"{p.name}: {len(rows)} lecturas leídas, {store.add_many(rows)} nuevas")


if __name__ == "__main__":
    main(sys.argv[1:])
