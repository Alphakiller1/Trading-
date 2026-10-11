"""How long to stay in: replay every leader buy signal on 1-minute candles under different exits.

    python tools/hold_fit.py            (engine also runs it every 6 hours)

For each recorded leader first-buy (signals table), a copier enters 30s after the leader at the next
1-minute candle's open and exits by one rule: a fixed timer (1-120 min), mirroring the leader's
first sell (+30s), a trailing stop, or a take-profit with a time cap. Returns are after fomo +
pump.fun fees and bonding-curve slippage at YOUR trade size (core/pump.py). Candle lows are
checked before highs inside a bar, so stops are scored pessimistically.
Writes model/hold_table.json, which the dashboard turns into each signal's hold plan.
"""
import collections, json, os, statistics, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import config, pump, store, model  # noqa: E402

CACHE = os.path.join(config.DATA, "candles")
OUT = os.path.join(ROOT, "model", "hold_table.json")
HORIZONS = [1, 2, 3, 5, 10, 15, 30, 60, 120]
DELAY = 30
os.makedirs(CACHE, exist_ok=True)


def candles(mint, start_ms):
    fn = os.path.join(CACHE, f"{mint}.json")
    if os.path.exists(fn):
        d = json.load(open(fn))
        if d["start"] <= start_ms and d["fetched"] > start_ms / 1000 + 130 * 60:
            return d["bars"]
    for _ in range(3):
        wait = pump.health["throttled_until"] - time.time()
        if wait > 0:
            time.sleep(min(wait + 1, 120))
        raw = pump.get(f"{pump.SW}/v2/coins/{mint}/candles", dict(interval="1m", limit=1000, currency="USD", createdTs=int(start_ms),
                                                                    program="pump", chainId=pump.CHAIN))
        if isinstance(raw, list):
            bars = [(int(b["timestamp"]) / 1000, float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"])) for b in raw
                    if all(b.get(k) is not None for k in ("timestamp", "open", "high", "low", "close"))]
            json.dump(dict(start=start_ms, fetched=time.time(), bars=bars), open(fn, "w"))
            return bars
    return None


def net(size, p_in, p_out):
    tok, lift = pump.buy_fill(size, p_in)
    return pump.sell_value(tok, p_out, lift) / size - 1


def replay(sig, bars, leader_sell_ts, size):
    t_in = sig["ts"] + DELAY
    i0 = next((i for i, b in enumerate(bars) if b[0] >= t_in - 59), None)      # bar containing the entry
    if i0 is None or i0 + 1 >= len(bars):
        return None
    p0 = bars[i0][1] if bars[i0][0] >= t_in else bars[i0][4]
    if p0 <= 0:
        return None
    path = bars[i0:i0 + 121]
    out = {}
    for h in HORIZONS:
        if h < len(path):
            out[f"time_{h}m"] = net(size, p0, path[h][4])
    if leader_sell_ts:
        j = next((k for k, b in enumerate(path) if b[0] >= leader_sell_ts + DELAY - 59), None)
        out["mirror_leader"] = net(size, p0, path[j][4] if j is not None else path[-1][4])
    else:
        out["mirror_leader"] = out.get("time_120m")
    for trail in (0.25, 0.40):
        peak, ex = p0, None
        for b in path[1:]:
            stop = peak * (1 - trail)
            if b[3] <= stop:
                ex = stop; break
            peak = max(peak, b[2])
        out[f"trail_{int(trail * 100)}"] = net(size, p0, ex if ex else path[-1][4])
    for tpp in (0.25, 0.50):                       # take profit, optional stop, hard time cap
        for slp in (None, 0.25):
            for cap in (5, 10):
                ex = None
                for b in path[1:cap + 1]:
                    if slp and b[3] <= p0 * (1 - slp):
                        ex = p0 * (1 - slp); break     # low checked first: pessimistic
                    if b[2] >= p0 * (1 + tpp):
                        ex = p0 * (1 + tpp); break
                name = f"tp{int(tpp * 100)}{'_sl' + str(int(slp * 100)) if slp else ''}_{cap}m"
                out[name] = net(size, p0, ex if ex else path[min(cap, len(path) - 1)][4])
    tp = p0 * 1.5; ex = None
    for b in path[1:16]:
        if b[2] >= tp:
            ex = tp; break
    out["tp50_or_15m"] = net(size, p0, ex if ex else path[min(15, len(path) - 1)][4])
    highs = [b[2] for b in path]
    k = max(range(len(highs)), key=lambda x: highs[x])
    out["peak_min"] = k
    out["peak_gain"] = highs[k] / p0 - 1
    out["dip_before_peak"] = min(b[3] for b in path[:k + 1]) / p0 - 1
    return out


def summary(rows, key):
    v = sorted(r[key] for r in rows if r.get(key) is not None)
    if not v:
        return None
    k = len(v) // 50
    t = v[:len(v) - k] if k else v
    return dict(n=len(v), mean=statistics.mean(v), trim=statistics.mean(t), median=statistics.median(v), win=sum(x > 0 for x in v) / len(v))


def main():
    size = float(sys.argv[1]) if len(sys.argv) > 1 else model.your_size()
    sigs = store.q("SELECT * FROM signals WHERE side='buy' AND role='leader' AND verdict!='ADD' ORDER BY ts")
    sells = {}
    for s in store.q("SELECT wallet, mint, ts FROM signals WHERE side='sell' ORDER BY ts"):
        sells.setdefault((s["wallet"], s["mint"]), []).append(s["ts"])
    first = {}
    for s in sigs:
        first.setdefault(s["mint"], s["ts"])
    rows = []
    for n, (mint, t0) in enumerate(first.items()):
        bars = candles(mint, (t0 - 120) * 1000)
        if not bars:
            continue
        for s in (x for x in sigs if x["mint"] == mint):
            if time.time() - s["ts"] < 125 * 60:
                continue                          # outcome not finished yet
            ls = next((t for t in sells.get((s["wallet"], mint), []) if t > s["ts"]), None)
            r = replay(s, bars, ls, size)
            if r:
                mv = (json.loads(s["intel"] or "{}") or {}).get("model") or {}
                r.update(verdict=s["verdict"], ev_pos=(mv.get("copier_ev") or -1) > 0, leader_sold=ls is not None)
                rows.append(r)
        if n % 25 == 0:
            print(f"coins {n}/{len(first)} · replays {len(rows)}", flush=True)
    rules = [f"time_{h}m" for h in HORIZONS] + ["mirror_leader", "trail_25", "trail_40", "tp50_or_15m"] +         [f"tp{t}{s}_{c}m" for t in (25, 50) for s in ("", "_sl25") for c in (5, 10)]
    groups = {"all": rows, "GO": [r for r in rows if r["verdict"] == "GO"], "CAUTION": [r for r in rows if r["verdict"] == "CAUTION"],
              "SKIP": [r for r in rows if r["verdict"] == "SKIP"], "positive_EV": [r for r in rows if r["ev_pos"]],
              "not_SKIP": [r for r in rows if r["verdict"] != "SKIP"]}
    table = {}
    for g, rs in groups.items():
        if len(rs) < 5:
            continue
        rr = {k: summary(rs, k) for k in rules}
        best = max((k for k in rules if rr[k]), key=lambda k: rr[k]["trim"])
        pk = sorted(r["peak_min"] for r in rs)
        table[g] = dict(n=len(rs), rules=rr, best=best,
                        peak_min=dict(p25=pk[len(pk) // 4], median=pk[len(pk) // 2], p75=pk[3 * len(pk) // 4]),
                        peak_gain_median=statistics.median(r["peak_gain"] for r in rs),
                        dip_before_peak_median=statistics.median(r["dip_before_peak"] for r in rs))
    span = (min(s["ts"] for s in sigs), max(s["ts"] for s in sigs)) if sigs else (0, 0)
    out = dict(built=time.time(), size=size, delay_s=DELAY, signals=len(rows), span=span, groups=table)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    for g, t in table.items():
        print(f"\n== {g}: {t['n']} replays · best rule {t['best']} · peak at {t['peak_min']['median']} min (middle half {t['peak_min']['p25']}-{t['peak_min']['p75']}) · "
              f"median peak +{t['peak_gain_median']:.0%} · median dip before peak {t['dip_before_peak_median']:.0%}")
        for k in rules:
            s = t["rules"][k]
            if s:
                print(f"   {k:14s} mean {s['mean']:+7.1%}  trim2% {s['trim']:+7.1%}  median {s['median']:+7.1%}  win {s['win']:4.0%}  n={s['n']}")
    return out


if __name__ == "__main__":
    main()
