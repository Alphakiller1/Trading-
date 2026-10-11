"""Copier's out-of-sample result for walk-forward-selected leaders, on real trade tapes.

Input: wf_rows.json from walkforward_days.py (each row = a position a leader OPENED on a test day,
where the leader qualified using only positions exited before that day). For every row since
--since, fetch the coin's tape, find the leader's first buy, and replay a copy: enter at the first
trade at/after (buy + delay), exit at the first trade at/after (leader's first sell + delay), else
mark at the last tape price. Costs/curve model from copysim.py.
"""
import json, os, sys, random, statistics, collections, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import pf
from copysim_costs import buy_tokens, sell_usd

SINCE = "2026-09-01"
SIZE = 190.0
DELAYS = (5, 10, 30, 60)
RULES = ["train ROI > 20%, win >= 40%, n >= 10", "all small wallets (baseline)"]
CAP = {"all small wallets (baseline)": 150}

R = json.load(open("wf_rows.json"))
random.seed(7)
todo = {}
for rule in RULES:
    rows = [r for r in R[rule] if r["o"][:10] >= SINCE]
    if rule in CAP and len(rows) > CAP[rule]:
        rows = random.sample(rows, CAP[rule])
    todo[rule] = rows
mints = {r["mint"] for rows in todo.values() for r in rows}
os.makedirs("tapes_wf", exist_ok=True)
print({k: len(v) for k, v in todo.items()}, "coins", len(mints), flush=True)


def fetch(m):
    fn = f"tapes_wf/{m}.json"
    if not os.path.exists(fn):
        tr, trunc = pf.coin_trades(m, max_pages=100)
        json.dump(dict(mint=m, truncated=trunc, trades=tr), open(fn, "w"))


with ThreadPoolExecutor(1) as ex:
    for i, _ in enumerate(ex.map(fetch, mints)):
        if i % 200 == 0:
            print("tapes", i, flush=True)


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def first_at(tr, t, i0=0):
    for x in tr[i0:]:
        if x["t"] >= t:
            return x["px"]
    return None


cache = {}
def tape(m):
    if m not in cache:
        d = json.load(open(f"tapes_wf/{m}.json"))
        cache[m] = None if d["truncated"] else [dict(x, t=ts(x["ts"])) for x in d["trades"]]
    return cache[m]


out = collections.defaultdict(lambda: collections.defaultdict(list))
missing = collections.Counter()
used = collections.defaultdict(list)      # rows that made it into the replay, to measure selection bias
for rule, rows in todo.items():
    for r in rows:
        tr = tape(r["mint"])
        if tr is None:          # incomplete or capped tape: the leader's entry may be missing
            missing[rule] += 1
            continue
        i = next((k for k, x in enumerate(tr) if x["w"] == r["w"] and x["side"] == "buy"), None)
        if i is None:
            missing[rule] += 1
            continue
        b = tr[i]
        used[rule].append(r)
        s = next((y for y in tr[i + 1:] if y["w"] == r["w"] and y["side"] == "sell"), None)
        for d in DELAYS:
            p_in = first_at(tr, b["t"] + d, i)
            if not p_in:
                continue
            p_out = (first_at(tr, s["t"] + d) if s else None) or tr[-1]["px"]
            tok, lift = buy_tokens(SIZE, p_in)
            out[rule][d].append(dict(roi=sell_usd(tok, p_out * lift) / SIZE - 1, w=r["w"], day=r["o"][:10],
                                     leader=((s["px"] if s else tr[-1]["px"]) / b["px"] - 1)))

print(f"\nCopier result at ${SIZE:.0f}/trade, positions opened since {SINCE} (walk-forward-selected leaders)")
for rule in RULES:
    print(f"\n{rule}  (leader buy not found in tape: {missing[rule]})")
    for d in DELAYS:
        rows = out[rule][d]
        if not rows:
            continue
        rois = sorted(x["roi"] for x in rows)
        k = len(rois) // 50
        byw = collections.defaultdict(list)
        for x in rows:
            byw[x["w"]].append(x["roi"])
        G = list(byw.values()); random.seed(3)
        boots = sorted(statistics.mean([v for g in (random.choice(G) for _ in G) for v in g]) for _ in range(1000))
        print(f"  delay {d:>2}s n={len(rows):5d} wallets={len(G):4d} mean {statistics.mean(rois):+6.1%} "
              f"CI[{boots[25]:+.1%},{boots[974]:+.1%}] trim2% {statistics.mean(rois[:len(rois) - k] if k else rois):+6.1%} "
              f"median {statistics.median(rois):+6.1%} win {sum(v > 0 for v in rois) / len(rois):5.1%} | leader {statistics.mean(x['leader'] for x in rows):+6.1%}")
json.dump({r: {str(d): v for d, v in dd.items()} for r, dd in out.items()}, open("copy_wf_rows.json", "w"))
