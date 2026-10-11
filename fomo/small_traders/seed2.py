"""Stage 1b: wallet discovery - latest 500 trades of the most actively traded sub-$80k coins."""
import json, os
from concurrent.futures import ThreadPoolExecutor
import pf
coins = {}
for sort in ("last_trade_timestamp", "created_timestamp"):
    for c in pf.list_coins(sort):
        coins.setdefault(c["mint"], c)
act = [c for c in coins.values() if c.get("program") == "pump" and (c.get("usd_market_cap") or 0) < 80000
       and (c.get("usd_market_cap") or 0) > 6000]
act.sort(key=lambda c: -(c.get("last_trade_timestamp") or 0))
print("active sub-80k coins", len(act), flush=True)
os.makedirs("disc", exist_ok=True)
def work(c):
    fn = f"disc/{c['mint']}.json"
    if os.path.exists(fn): return
    tr, trunc = pf.coin_trades(c["mint"], max_pages=5)
    json.dump(dict(mint=c["mint"], truncated=trunc, trades=tr), open(fn, "w"))
n = 0
with ThreadPoolExecutor(8) as ex:
    for _ in ex.map(work, act):
        n += 1
        if n % 50 == 0: print("disc", n, flush=True)
print("DONE", n, flush=True)
