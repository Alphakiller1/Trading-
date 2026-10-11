"""Day-level walk-forward of small-trader skill on sub-$80k pump.fun coins.

Selection for test day D uses ONLY positions fully exited before D (no open positions, no
outcomes after D). The test scores those wallets' positions DATED on day D. pump.fun's portfolio
rarely carries openedAt, so a position is dated by updatedAt, which equals the wallet's last
trade in the coin (verified against tapes: median difference 0s). For closed positions that is
the EXIT day. A wallet qualifies for the user's size rules only if, across its whole
history, no position took more than $1k of buys and no day took more than $5k.
"""
import glob, json, collections, datetime as dt, random, statistics, sys

SOL_CHAIN = 1399811149
MAX_POS_USD, MAX_DAY_USD, MAX_ENTRY_MCAP = 1000, 5000, 80000


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


wallets = {}
skipped = 0
for fn in glob.glob("portfolios/*.json"):
    d = json.load(open(fn))
    if d.get("skipped"):
        skipped += 1
        continue
    rows, day_spend, max_pos = [], collections.Counter(), 0.0
    for p in d["positions"]:
        if p.get("chainId") != SOL_CHAIN:
            continue
        bought, qty = p.get("amountBoughtUsd") or 0, p.get("amountBought") or 0
        u = ts(p.get("updatedAt"))
        o = ts(p.get("openedAt")) or u  # openedAt is often missing; last-trade time as fallback
        if bought <= 0 or qty <= 0 or o is None:
            continue
        day_spend[o.date()] += bought
        max_pos = max(max_pos, bought)
        if p.get("hasTransfers") or p.get("hasUntrustedUsdBasis") or p.get("potentialSpam"):
            continue
        if p.get("program") != "pump" and not str(p["coinMint"]).endswith("pump"):
            continue
        mcap = bought / qty * 1e9
        if mcap >= MAX_ENTRY_MCAP:
            continue
        rows.append(dict(w=d["wallet"], o=o, u=u, exited=bool(p.get("isExited")), bought=bought,
                         pnl=p.get("pnlUsd") or 0.0, mcap=mcap, mint=p["coinMint"]))
    if not rows:
        continue
    med_mcap = statistics.median(r["mcap"] for r in rows)
    wallets[d["wallet"]] = dict(rows=rows, sniper=med_mcap < 4500,
                                small=max_pos <= MAX_POS_USD and max(day_spend.values()) <= MAX_DAY_USD)

print(f"wallets with sub-$80k pump positions: {len(wallets)}  (skipped >1000 positions: {skipped})")
print(f"launch snipers (median entry mcap < $4.5k, not copyable at app speed): {sum(w['sniper'] for w in wallets.values())}")
for w in wallets.values():
    w["small"] = w["small"] and not w["sniper"]
print(f"meeting size rules (every position <= $1k, every day <= $5k): {sum(w['small'] for w in wallets.values())}")
allrows = [r for w in wallets.values() if w["small"] for r in w["rows"]]
days = sorted({r["o"].date() for r in allrows})
print("position days (exit day for closed positions):", days[0], "->", days[-1], " positions:", len(allrows))


def roi(rows):
    b = sum(r["bought"] for r in rows)
    return sum(r["pnl"] for r in rows) / b if b else float("nan")


def trim(rows, frac=0.02):
    k = int(len(rows) * frac)
    return sorted(rows, key=lambda r: r["pnl"] / r["bought"])[:len(rows) - k] if k else rows


RULES = {
    "all small wallets (baseline)": lambda tr: len(tr) >= 1,
    "train ROI > 0, n >= 10": lambda tr: len(tr) >= 10 and roi(tr) > 0,
    "train ROI > 20%, win >= 40%, n >= 10": lambda tr: len(tr) >= 10 and roi(tr) > .2 and
        sum(r["pnl"] > 0 for r in tr) / len(tr) >= .4,
    "train ROI > 0, n >= 25": lambda tr: len(tr) >= 25 and roi(tr) > 0,
    "train ROI <= 0, n >= 10 (losers)": lambda tr: len(tr) >= 10 and roi(tr) <= 0,
}

test_days = [d for d in days if d >= days[0] + dt.timedelta(days=5)][:-1]  # today is still open
res = {k: [] for k in RULES}
per_day = {k: collections.OrderedDict() for k in RULES}
for D in test_days:
    cut = dt.datetime.combine(D, dt.time(0), tzinfo=dt.timezone.utc)
    for name, rule in RULES.items():
        rows = []
        for w in wallets.values():
            if not w["small"]:
                continue
            tr = [r for r in w["rows"] if r["exited"] and r["u"] and r["u"] < cut and r["o"] >= cut - dt.timedelta(days=14)]
            if rule(tr):
                rows += [r for r in w["rows"] if r["o"].date() == D]
        res[name] += rows
        per_day[name][str(D)] = (len(rows), roi(rows))

print(f"\nWalk-forward over test days {test_days[0]} .. {test_days[-1]} (leader's own result, before any copy costs)")
print(f"{'rule':42s} {'n':>6s} {'ROI':>8s} {'trim2%':>8s} {'median':>8s} {'win%':>6s}")
for name, rows in res.items():
    if not rows:
        print(f"{name:42s} {0:6d}"); continue
    med = statistics.median(r["pnl"] / r["bought"] for r in rows)
    win = sum(r["pnl"] > 0 for r in rows) / len(rows)
    print(f"{name:42s} {len(rows):6d} {roi(rows):8.1%} {roi(trim(rows)):8.1%} {med:8.1%} {win:6.1%}")
print("\nPer test day (n, ROI):")
for name in RULES:
    print(" ", name[:40].ljust(40), " ".join(f"{d[5:]}:{n}/{r:+.0%}" for d, (n, r) in per_day[name].items() if n))

# wallet-clustered bootstrap CI (resample wallets, not positions)
for main in ("train ROI > 0, n >= 10", "all small wallets (baseline)"):
    byw = collections.defaultdict(list)
    for r in res[main]:
        byw[r["w"]].append(r)
    groups = list(byw.values())
    if len(groups) < 5:
        continue
    random.seed(1)
    boots = sorted(roi([r for g in (random.choice(groups) for _ in groups) for r in g]) for _ in range(2000))
    print(f"Wallet-clustered 95% CI, {main}: {boots[50]:.1%} .. {boots[1949]:.1%} ({len(groups)} wallets)")
json.dump({k: [dict(r, o=str(r["o"]), u=str(r["u"])) for r in v] for k, v in res.items()}, open("wf_rows.json", "w"))
