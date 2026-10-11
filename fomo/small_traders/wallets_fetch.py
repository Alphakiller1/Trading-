"""Stage 2: pick small-size candidate wallets from the coin tapes and pull their full multi-week
position history from pump.fun's public portfolio endpoint (read-only)."""
import glob, json, os, collections, sys
from concurrent.futures import ThreadPoolExecutor
import pf

MAX_TRADE_USD = 1000
os.makedirs("portfolios", exist_ok=True)

buys = collections.defaultdict(list)      # wallet -> buy sizes seen in tapes
coins_by_w = collections.defaultdict(set)
for fn in glob.glob("tapes/*.json") + glob.glob("disc/*.json"):
    d = json.load(open(fn))
    for t in d["trades"]:
        if t["side"] == "buy":
            buys[t["w"]].append(t["usd"])
            coins_by_w[t["w"]].add(d["mint"])

cands = [w for w, b in buys.items()
         if max(b) <= MAX_TRADE_USD and sorted(b)[len(b) // 2] >= 10 and len(coins_by_w[w]) >= 1]
cands.sort(key=lambda w: -len(coins_by_w[w]))
limit = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
cands = cands[:limit]
print("wallets in tapes", len(buys), "candidates", len(cands), flush=True)


def work(w):
    fn = f"portfolios/{w}.json"
    if os.path.exists(fn):
        return
    first = pf.get(f"{pf.FE}/user-portfolio/{w}", dict(filter="all", page=0, pageSize=100, sortBy="PNL"))
    count = ((first or {}).get("summary") or {}).get("positionCount")
    if not first or count is None or count > 2500:
        json.dump(dict(wallet=w, count=count, skipped=True), open(fn, "w"))
        return
    pos = pf.portfolio(w, pages=25)
    json.dump(dict(wallet=w, count=count, positions=pos), open(fn, "w"))


n = 0
with ThreadPoolExecutor(6) as ex:
    for _ in ex.map(work, cands):
        n += 1
        if n % 200 == 0:
            print("portfolios", n, flush=True)
print("DONE", n, flush=True)
