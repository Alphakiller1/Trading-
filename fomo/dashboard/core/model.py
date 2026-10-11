"""Signal EV from model/ev_table.json (fit by tools/model_fit.py, walk-forward validated).

A cell is (leader class, entry market cap, leader position size). The table holds the leader-side
ROI per cell; a copier earns that minus the copy penalty: round-trip cost at YOUR size + delay
drift. Small cells are shrunk toward a pessimistic prior so thin evidence can't produce a GO.
"""
import json, os
from . import config, pump, store

PATH = os.path.join(config.ROOT, "model", "ev_table.json")
PRIOR, K, DRIFT = -0.05, 100, 0.015
_t = {"mtime": 0, "data": None}


def _load():
    try:
        m = os.path.getmtime(PATH)
        if m != _t["mtime"]:
            _t.update(mtime=m, data=json.load(open(PATH)))
    except Exception:
        _t["data"] = None
    return _t["data"]


def lclass(n, roi, win):
    if not n or n < 10: return "new"
    if roi <= 0: return "loser"
    if roi <= 0.20: return "small_winner"
    return "strict" if win >= 0.40 else "streaky"


def mcap_b(m):
    return "<10k" if m < 10000 else ("10-25k" if m < 25000 else "25-80k")


def size_b(s):
    return "<$25" if s < 25 else ("$25-100" if s < 100 else "$100+")


def your_size():
    """Median of your last 20 real trades (what you actually bet), else the Settings trade size."""
    rows = [r["size_usd"] for r in store.q("SELECT size_usd FROM trades WHERE mode='real' AND size_usd>0 ORDER BY opened_at DESC LIMIT 20")]
    if len(rows) >= 5:
        rows.sort()
        return rows[len(rows) // 2]
    return config.load()["trade_size_usd"]


def ev(leader, mcap, leader_usd, size_usd=None):
    """Expected copier ROI for this signal, or None if the model can't place it."""
    d = _load()
    if not d or mcap is None or leader_usd is None or mcap >= 80000:
        return None
    size_usd = size_usd or your_size()
    cls = lclass(leader.get("closed_14d"), leader.get("roi_14d") or 0, leader.get("win_rate") or 0)
    cell = (cls, mcap_b(mcap), size_b(leader_usd))
    c = d["cells"].get("|".join(cell))
    n, mean = (c["n"], c["mean"]) if c else (0, PRIOR)
    shrunk = (n * mean + K * PRIOR) / (n + K)
    v = d.get("validation", {}).get("|".join(cell)) or {}
    penalty = pump.round_trip_cost(max(5, size_usd), mcap) + DRIFT
    return dict(cell=list(cell), n=n, leader_mean=mean, shrunk=shrunk, penalty=penalty,
                copier_ev=shrunk - penalty, win=(c or {}).get("win"),
                test=(v.get("test") or {}).get("mean"), test_n=(v.get("test") or {}).get("n"))
