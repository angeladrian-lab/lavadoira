"""Histórico de lecturas de potencia en SQLite (history.db). Lo usan el monitor, el importador y el dashboard."""
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("HISTORY_DB") or Path(__file__).with_name("history.db"))


def connect():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        "CREATE TABLE IF NOT EXISTS readings ("
        "appliance TEXT NOT NULL, ts INTEGER NOT NULL, watts REAL NOT NULL, "
        "PRIMARY KEY (appliance, ts))"
    )
    return db


def add_many(rows):
    """rows: iterable de (appliance, ts_epoch_seg, watts). Ignora duplicados. Devuelve cuántas filas nuevas hubo."""
    db = connect()
    with db:
        before = db.total_changes
        db.executemany("INSERT OR IGNORE INTO readings VALUES (?,?,?)", rows)
        added = db.total_changes - before
    db.close()
    return added


def fetch(appliance, since_ts=0):
    db = connect()
    rows = db.execute(
        "SELECT ts, watts FROM readings WHERE appliance=? AND ts>=? ORDER BY ts", (appliance, int(since_ts))
    ).fetchall()
    db.close()
    return rows
