"""SQLite storage: leaders, signals, trades (paper + real), alerts, seen transactions."""
import json, os, sqlite3, threading, time
from . import config

DB = os.path.join(config.DATA, "fomo.db")
_lock = threading.RLock()
_conn = sqlite3.connect(DB, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.executescript("""
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS leaders(
  wallet TEXT PRIMARY KEY, label TEXT, closed_14d INT, roi_14d REAL, win_rate REAL,
  median_size REAL, median_mcap REAL, enabled INT DEFAULT 1, source TEXT, updated_at REAL,
  last_trade_at REAL, note TEXT);
CREATE TABLE IF NOT EXISTS signals(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, wallet TEXT, role TEXT, mint TEXT, symbol TEXT,
  side TEXT, usd REAL, mcap REAL, verdict TEXT, score INT, reasons TEXT, intel TEXT, tx TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS trades(
  id INTEGER PRIMARY KEY AUTOINCREMENT, mode TEXT, mint TEXT, symbol TEXT, leader TEXT, signal_id INT,
  opened_at REAL, entry_mcap REAL, size_usd REAL, tokens REAL, lift REAL, status TEXT,
  closed_at REAL, exit_mcap REAL, proceeds_usd REAL, pnl_usd REAL, roi REAL, exit_reason TEXT,
  last_mcap REAL, peak_mcap REAL, notes TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, level TEXT, kind TEXT, title TEXT, body TEXT,
  mint TEXT, read INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS seen(sig TEXT PRIMARY KEY, wallet TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS ix_sig_ts ON signals(ts);
CREATE INDEX IF NOT EXISTS ix_tr_status ON trades(status);
""")
_conn.commit()


def q(sql, args=()):
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def one(sql, args=()):
    r = q(sql, args)
    return r[0] if r else None


def run(sql, args=()):
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid


def insert(table, row):
    keys = list(row)
    return run(f"INSERT OR IGNORE INTO {table}({','.join(keys)}) VALUES({','.join('?' * len(keys))})",
               [json.dumps(v) if isinstance(v, (dict, list)) else v for v in row.values()])


def update(table, key, kv, row):
    sets = ",".join(f"{k}=?" for k in row)
    run(f"UPDATE {table} SET {sets} WHERE {key}=?", list(row.values()) + [kv])


def alert(level, kind, title, body="", mint=None):
    return insert("alerts", dict(ts=time.time(), level=level, kind=kind, title=title, body=body, mint=mint))
