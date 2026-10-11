"""Out-of-sample copy simulation on today's real trade tapes.

Leaders are chosen ONLY from positions fully exited before today 00:00 UTC (same size rules as
walkforward_days.py). Today's tapes are then replayed: when a leader makes its first buy in a coin
under $80k, the copier buys at the first trade price at/after (leader time + delay) and sells at
the first trade price at/after (leader's first sell + delay). Costs: fomo fee tiers, pump.fun 1.25% per
side and constant-product slippage on the bonding curve. Open copies are marked at the last tape price.
"""
import glob, json, datetime as dt, statistics, collections, sys
import walkforward_days as wf  # reuses its parsed wallets (prints its own report on import)

SIZE = float(sys.argv[1]) if len(sys.argv) > 1 else 190.0
DELAYS = (5, 10, 30, 60)
cut = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def qualified(rule):
    out = set()
    for w, wd in wf.wallets.items():
        if not wd["small"]:
            continue
        tr = [r for r in wd["rows"] if r["exited"] and r["u"] and r["u"] < cut and r["o"] >= cut - dt.timedelta(days=14)]
        if rule(tr):
            out.add(w)
    return out


SOLUSD, K = 110.0, 30 * 1.073e9   # pump.fun curve: 30 virtual SOL x 1.073B virtual tokens
PUMP_FEE = 0.0125                  # conservative (sources say 1.0-1.25% per side)


def fomo_fee(usd):                 # same tiers as Trading-/fomo/backtest.py
    if usd < 5: return 0.10
    if usd < 47.5: return usd * 0.02
    if usd < 190: return 0.95
    return usd * 0.005


def buy_tokens(usd, px):           # constant-product fill at the curve state implied by px
    """Returns (tokens, lift): lift is how much our own buy raises the curve price, which the tape
    prices we later sell into do not include (same treatment as Trading-/fomo/strategies.py)."""
    x = (usd - fomo_fee(usd)) * (1 - PUMP_FEE) / SOLUSD
    vS = (px / SOLUSD * K) ** 0.5; vT = K / vS
    return vT - K / (vS + x), ((vS + x) / vS) ** 2


def sell_usd(tokens, px):
    vS = (px / SOLUSD * K) ** 0.5; vT = K / vS
    usd = (vS - K / (vT + tokens)) * SOLUSD * (1 - PUMP_FEE)
    return usd - fomo_fee(usd)


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


tapes = {}
for fn in glob.glob("disc/*.json") + glob.glob("tapes/*.json"):
    d = json.load(open(fn))
    tr = [dict(t, t=ts(t["ts"])) for t in d["trades"]]
    if tr:
        tapes[d["mint"]] = tr


def px_at(tr, t):
    for x in tr:
        if x["t"] >= t:
            return x["px"]
    return None


def sim(leaders):
    res = {d: [] for d in DELAYS}
    for mint, tr in tapes.items():
        seen = set()
        for i, x in enumerate(tr):
            if x["w"] not in leaders or x["w"] in seen or x["side"] != "buy" or x["t"] < cut.timestamp():
                continue
            if x["px"] * 1e9 >= 80000:
                continue
            seen.add(x["w"])
            sell = next((y for y in tr[i + 1:] if y["w"] == x["w"] and y["side"] == "sell"), None)
            for d in DELAYS:
                p_in = px_at(tr, x["t"] + d)
                if not p_in:
                    continue
                p_out = px_at(tr, sell["t"] + d) if sell else None
                p_out = p_out or tr[-1]["px"]
                tok, lift = buy_tokens(SIZE, p_in)
                back = sell_usd(tok, p_out * lift)
                res[d].append(dict(mint=mint, w=x["w"], roi=back / SIZE - 1,
                                   leader_roi=((sell["px"] if sell else tr[-1]["px"]) / x["px"] - 1),
                                   closed=bool(sell)))
    return res


RULES = {
    "all small wallets": lambda tr: len(tr) >= 1,
    "train ROI > 0, n >= 10": lambda tr: len(tr) >= 10 and wf.roi(tr) > 0,
    "train ROI > 20%, win >= 40%, n >= 10": lambda tr: len(tr) >= 10 and wf.roi(tr) > .2 and sum(r["pnl"] > 0 for r in tr) / len(tr) >= .4,
}
print(f"\n=== Copy simulation on today's tapes (after {cut:%Y-%m-%d %H:%M} UTC), ${SIZE:.0f} per trade ===")
for name, rule in RULES.items():
    L = qualified(rule)
    r = sim(L)
    print(f"\n{name}: {len(L)} leaders")
    for d in DELAYS:
        rows = r[d]
        if not rows:
            print(f"  delay {d:>2}s: no signals"); continue
        rois = sorted(x["roi"] for x in rows)
        k = max(1, len(rois) // 50) if len(rois) >= 50 else 0
        trimmed = rois[:len(rois) - k] if k else rois
        print(f"  delay {d:>2}s: n={len(rows):4d}  mean {statistics.mean(rois):+7.1%}  trim2% {statistics.mean(trimmed):+7.1%}"
              f"  median {statistics.median(rois):+7.1%}  win {sum(x > 0 for x in rois) / len(rois):5.1%}"
              f"  | leader's own mean {statistics.mean(x['leader_roi'] for x in rows):+7.1%}  closed {sum(x['closed'] for x in rows)}")
