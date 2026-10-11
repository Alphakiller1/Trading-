"""How late are signals, and what does lateness cost?

    python tools/latency_audit.py

For every leader buy signal: delay from the leader's on-chain buy to the dashboard's alert, and the
coin's market-cap move over that delay (1-minute candles). Replays the hold plan entering at the
leader's time vs at the alert time (+10s for you to act) to price the lateness. For your own real
trades that followed a signal: how long after the leader you bought and how much more you paid.
"""
import json, os, statistics, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
from core import store, pump, model  # noqa: E402
from hold_fit import candles  # noqa: E402

SIZE = model.your_size()


def bar_at(bars, t):
    for b in bars:
        if b[0] <= t < b[0] + 60:
            return b
    return None


def px_at(bars, t, field=1):
    """open of the bar containing t if t is at the bar start, else that bar's close (pessimistic for a late entry)."""
    b = bar_at(bars, t)
    if not b:
        return None
    return b[1] if t - b[0] < 15 else b[4]


def plan_return(bars, t_in, window=5, tp=None):
    p0 = px_at(bars, t_in)
    if not p0:
        return None
    i0 = next((i for i, b in enumerate(bars) if b[0] <= t_in < b[0] + 60), None)
    path = bars[i0:i0 + window + 1]
    if len(path) < 2:
        return None
    ex = None
    if tp:
        for b in path[1:]:
            if b[2] >= p0 * (1 + tp):
                ex = p0 * (1 + tp); break
    ex = ex or path[-1][4]
    tok, lift = pump.buy_fill(SIZE, p0)
    return pump.sell_value(tok, ex, lift) / SIZE - 1


def q(v, p):
    v = sorted(v); return v[min(len(v) - 1, int(p * len(v)))] if v else None


def main():
    sigs = store.q("SELECT id, ts, mint, symbol, verdict, intel FROM signals WHERE side='buy' AND role='leader' AND verdict!='ADD' ORDER BY ts")
    rows = []
    for s in sigs:
        a = store.one("SELECT MIN(ts) t FROM alerts WHERE mint=? AND kind IN ('GO','CAUTION','SKIP') AND ts>=?", (s["mint"], s["ts"]))
        if not a or not a["t"]:
            continue
        lag = a["t"] - s["ts"]
        if lag < 0 or lag > 900:          # >15 min: restart catch-up from before the stale-signal fix
            continue
        if time.time() - s["ts"] < 12 * 60:
            continue
        bars = candles(s["mint"], (s["ts"] - 120) * 1000)
        if not bars:
            continue
        p_lead, p_alert = px_at(bars, s["ts"]), px_at(bars, a["t"] + 10)
        if not p_lead or not p_alert:
            continue
        mv = (json.loads(s["intel"] or "{}") or {}).get("model") or {}
        rows.append(dict(lag=lag, move=p_alert / p_lead - 1, verdict=s["verdict"], ev_pos=(mv.get("copier_ev") or -1) > 0,
                         at_leader=plan_return(bars, s["ts"] + 3), at_alert=plan_return(bars, a["t"] + 10)))
    print(f"signals measured: {len(rows)}  (your size ${SIZE:.0f})")
    lags = [r["lag"] for r in rows]
    print(f"alert delay after the leader's buy: median {statistics.median(lags):.0f}s · p25 {q(lags, .25):.0f}s · p75 {q(lags, .75):.0f}s · p90 {q(lags, .9):.0f}s")
    mv = [r["move"] for r in rows]
    print(f"coin's move between leader buy and your alert (+10s): median {statistics.median(mv):+.1%} · p75 {q(mv, .75):+.1%} · p90 {q(mv, .9):+.1%}")
    for name, sel in (("all", rows), ("positive EV", [r for r in rows if r["ev_pos"]]), ("not SKIP", [r for r in rows if r["verdict"] != "SKIP"])):
        a = [r["at_leader"] for r in sel if r["at_leader"] is not None and r["at_alert"] is not None]
        b = [r["at_alert"] for r in sel if r["at_leader"] is not None and r["at_alert"] is not None]
        if a:
            print(f"5-min plan, {name:12s}: entering 3s after the leader {statistics.mean(a):+.1%} mean / {statistics.median(a):+.1%} median"
                  f"  vs at the alert {statistics.mean(b):+.1%} / {statistics.median(b):+.1%}  (n={len(a)})")
    for lo, hi in ((0, 30), (30, 60), (60, 120), (120, 900)):
        sel = [r for r in rows if lo <= r["lag"] < hi and r["at_alert"] is not None]
        if sel:
            print(f"   alert {lo:>3}-{hi:<3}s late: n={len(sel):3d}  move before alert {statistics.median(r['move'] for r in sel):+6.1%}  plan result {statistics.mean(r['at_alert'] for r in sel):+6.1%}")
    # your own trades that followed a leader signal
    mine = store.q("SELECT t.*, s.ts sig_ts FROM trades t JOIN signals s ON s.id=t.signal_id WHERE t.mode='real' AND t.status='closed'")
    out = []
    for t in mine:
        bars = candles(t["mint"], (t["sig_ts"] - 120) * 1000)
        if not bars:
            continue
        pl, pm = px_at(bars, t["sig_ts"]), px_at(bars, t["opened_at"])
        if pl and pm:
            out.append(dict(delay=t["opened_at"] - t["sig_ts"], premium=pm / pl - 1, pnl=t["pnl_usd"] or 0, roi=t["roi"] or 0))
    if out:
        print(f"\nyour trades after a leader signal: {len(out)}")
        print(f"  you bought a median {statistics.median(o['delay'] for o in out) / 60:.1f} min after the leader, paying a median "
              f"{statistics.median(o['premium'] for o in out):+.1%} over the leader's price")
        for lo, hi in ((0, 60), (60, 300), (300, 1800), (1800, 4000)):
            sel = [o for o in out if lo <= o["delay"] < hi]
            if sel:
                print(f"   {lo // 60:>2}-{hi // 60:<2} min after: n={len(sel):2d}  premium {statistics.median(o['premium'] for o in sel):+6.1%}  "
                      f"your net ${sum(o['pnl'] for o in sel):+7.2f}  ROI {statistics.mean(o['roi'] for o in sel):+6.1%}")
    return rows, out


if __name__ == "__main__":
    main()
