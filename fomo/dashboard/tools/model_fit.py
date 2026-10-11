"""Fit the signal EV table: what is a small leader's buy worth, by leader class x entry mcap x leader size?

    python tools/model_fit.py [PORTFOLIOS_DIR]     (default: ../../../portfolios, from small_traders/wallets_fetch.py)

Each position is scored with the leader's trailing 14-day record built ONLY from positions closed
before that day (no look-ahead). Positions are dated by their last trade (pump.fun rarely records
an open time). The table is fit on positions before SPLIT and checked on positions after it.
Writes model/ev_table.json (leader-side ROI per cell). The dashboard subtracts your copy penalty
(fees at your size + delay drift) at serve time.
"""
import collections, datetime as dt, glob, json, os, statistics, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "..", "..", "portfolios")
SPLIT = dt.date(2026, 10, 1)
SINCE = dt.date(2026, 8, 1)
CLIP = (-1.0, 3.0)          # cap single-trade ROI at +300% so one moonshot can't define a cell
SOL = 1399811149


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def lclass(n, roi, win):
    if n < 10: return "new"
    if roi <= 0: return "loser"
    if roi <= 0.20: return "small_winner"
    return "strict" if win >= 0.40 else "streaky"


def mcap_b(m):
    return "<10k" if m < 10000 else ("10-25k" if m < 25000 else "25-80k")


def size_b(s):
    return "<$25" if s < 25 else ("$25-100" if s < 100 else "$100+")


def load():
    out = {}
    for fn in glob.glob(os.path.join(PDIR, "*.json")):
        d = json.load(open(fn))
        if d.get("skipped"):
            continue
        rows, day, mx = [], collections.Counter(), 0.0
        for p in d.get("positions", []):
            if p.get("chainId") != SOL:
                continue
            b, q = p.get("amountBoughtUsd") or 0, p.get("amountBought") or 0
            u = ts(p.get("updatedAt")); o = ts(p.get("openedAt")) or u
            if b <= 0 or q <= 0 or o is None:
                continue
            day[o.date()] += b; mx = max(mx, b)
            if p.get("hasTransfers") or p.get("hasUntrustedUsdBasis") or p.get("potentialSpam"):
                continue
            if p.get("program") != "pump" and not str(p["coinMint"]).endswith("pump"):
                continue
            mc = b / q * 1e9
            if mc >= 80000:
                continue
            rows.append(dict(u=u, ex=bool(p.get("isExited")), b=b, pnl=p.get("pnlUsd") or 0.0, mc=mc))
        if rows and mx <= 1000 and max(day.values()) <= 5000 and statistics.median(r["mc"] for r in rows) >= 4500:
            out[d["wallet"]] = sorted(rows, key=lambda r: r["u"])
    return out


def samples(wallets):
    S = []
    for w, rows in wallets.items():
        closed = [r for r in rows if r["ex"]]
        for r in rows:
            d = r["u"].date()
            if d < SINCE:
                continue
            cut = dt.datetime.combine(d, dt.time(0), tzinfo=dt.timezone.utc)
            tr = [x for x in closed if cut - dt.timedelta(days=14) <= x["u"] < cut]
            b = sum(x["b"] for x in tr)
            roi = sum(x["pnl"] for x in tr) / b if b else 0.0
            win = sum(x["pnl"] > 0 for x in tr) / len(tr) if tr else 0.0
            y = min(CLIP[1], max(CLIP[0], r["pnl"] / r["b"]))
            S.append(dict(d=d, w=w, cell=(lclass(len(tr), roi, win), mcap_b(r["mc"]), size_b(r["b"])), y=y))
    return S


def table(S):
    g = collections.defaultdict(list)
    for s in S:
        g[s["cell"]].append(s["y"])
    return {c: dict(n=len(v), mean=statistics.mean(v), median=statistics.median(v), win=sum(x > 0 for x in v) / len(v)) for c, v in g.items()}


def main():
    W = load()
    S = samples(W)
    tr = [s for s in S if s["d"] < SPLIT]; te = [s for s in S if s["d"] >= SPLIT]
    T, V = table(tr), table(te)
    print(f"small wallets {len(W)} | samples {len(S)} (fit {len(tr)} before {SPLIT}, test {len(te)} after)")
    print(f"\n{'cell (leader class, entry mcap, leader size)':52s} {'fit n':>6s} {'fit mean':>9s} {'test n':>6s} {'test mean':>9s} {'test win':>8s}")
    for c in sorted(T, key=lambda c: -T[c]["mean"]):
        if T[c]["n"] < 30:
            continue
        v = V.get(c, dict(n=0, mean=float("nan"), win=float("nan")))
        print(f"{str(c):52s} {T[c]['n']:6d} {T[c]['mean']:+9.1%} {v['n']:6d} {v['mean']:+9.1%} {v['win']:8.0%}")
    # out-of-sample check: does the fit ranking hold on the test month?
    cells = [c for c in T if T[c]["n"] >= 30 and V.get(c, {}).get("n", 0) >= 30]
    if len(cells) >= 4:
        a = sorted(cells, key=lambda c: T[c]["mean"]); b = sorted(cells, key=lambda c: V[c]["mean"])
        ra = {c: i for i, c in enumerate(a)}; rb = {c: i for i, c in enumerate(b)}
        n = len(cells); rho = 1 - 6 * sum((ra[c] - rb[c]) ** 2 for c in cells) / (n * (n * n - 1))
        top = [c for c in cells if T[c]["mean"] >= sorted(T[x]["mean"] for x in cells)[-max(1, n // 4)]]
        te_top = [s["y"] for s in te if s["cell"] in top]
        te_all = [s["y"] for s in te if s["cell"] in cells]
        print(f"\nRank correlation fit vs test across {n} cells: {rho:+.2f}")
        print(f"Test month, top-quarter cells by fit: mean {statistics.mean(te_top):+.1%} (n={len(te_top)}) vs all cells {statistics.mean(te_all):+.1%} (n={len(te_all)})")
    full = table(S)
    out = dict(built=str(dt.date.today()), fit_before=str(SPLIT), clip=CLIP, samples=len(S),
               cells={"|".join(c): v for c, v in full.items() if v["n"] >= 20},
               validation={"|".join(c): dict(fit=T[c], test=V.get(c)) for c in T if T[c]["n"] >= 30})
    os.makedirs(os.path.join(HERE, "model"), exist_ok=True)
    json.dump(out, open(os.path.join(HERE, "model", "ev_table.json"), "w"), indent=1)
    print(f"\nWrote model/ev_table.json ({len(out['cells'])} cells)")


if __name__ == "__main__":
    main()
