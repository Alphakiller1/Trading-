"""Which market zones pay: replay leader signals by coin age x market cap.

    python tools/zone_fit.py            (engine also runs it every 6 hours)

Zone = coin age at the signal (brand new < 5 min, early 5-60 min, young 1-6 h, mature 6 h+)
x market cap (< $15k, $15k-80k, > $80k). Each signal is replayed buying 3s after the leader (what
the push feed now allows) and selling 5 minutes later, after fees at your size, on pump.fun
1-minute candles. Writes model/zone_table.json; the dashboard tags every signal with its zone.
"""
import collections, json, os, statistics, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
from core import store, pump, model, zones  # noqa: E402
from hold_fit import candles  # noqa: E402

OUT = os.path.join(ROOT, "model", "zone_table.json")


def main():
    size = model.your_size()
    rows = []
    for s in store.q("SELECT ts, mint, intel FROM signals WHERE side='buy' AND role='leader' AND verdict!='ADD' ORDER BY ts"):
        if time.time() - s["ts"] < 8 * 60:
            continue
        m = (json.loads(s["intel"] or "{}") or {}).get("m") or {}
        if m.get("age_min") is None or not m.get("mcap"):
            continue
        bars = candles(s["mint"], (s["ts"] - 120) * 1000)
        if not bars:
            continue
        t = s["ts"] + 3
        i = next((k for k, b in enumerate(bars) if b[0] <= t < b[0] + 60), None)
        if i is None or i + 5 >= len(bars):
            continue
        p0 = bars[i][1] if t - bars[i][0] < 15 else bars[i][4]
        if p0 <= 0:
            continue
        tok, lift = pump.buy_fill(size, p0)
        rows.append((zones.label(m["age_min"], m["mcap"]), pump.sell_value(tok, bars[i + 5][4], lift) / size - 1,
                     max(b[2] for b in bars[i:i + 11]) / p0 - 1))
    g = collections.defaultdict(list)
    for z, r, pk in rows:
        g[z].append((r, pk))
    table = {z: dict(n=len(v), mean=statistics.mean(r for r, _ in v), median=statistics.median(r for r, _ in v),
                     win=sum(r > 0 for r, _ in v) / len(v), peak10_median=statistics.median(pk for _, pk in v))
             for z, v in g.items()}
    out = dict(built=time.time(), size=size, n=len(rows), zones=table)
    json.dump(out, open(OUT, "w"), indent=1)
    for z, v in sorted(table.items(), key=lambda kv: -kv[1]["mean"]):
        print(f"{z:32s} n={v['n']:3d}  mean {v['mean']:+6.1%}  median {v['median']:+6.1%}  win {v['win']:4.0%}  10-min peak {v['peak10_median']:+6.1%}")
    return out


if __name__ == "__main__":
    main()
