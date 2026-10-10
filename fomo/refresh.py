# re-pull full tapes (up to 30 pages) for every collected coin, plus new launches, to get complete life cycles
import json, sys, concurrent.futures as cf
exec(open("collect.py").read().split("coins={}")[0])
coins=json.load(open("coins.json"))
for sort in ("created_timestamp","last_trade_timestamp"):
    for off in range(0,1000,50):
        d=get(f"{B}/coins",dict(offset=off,limit=50,sort=sort,order="DESC",includeNsfw="true"))
        if not d: break
        for c in d: coins.setdefault(c["mint"],c)
json.dump(coins,open("coins.json","w"))
now=time.time()*1000
cand=[m for m,c in coins.items() if c.get("program")=="pump" and now-c["created_timestamp"]<7*86400e3]
def trades(mint,maxpages=30):
    out=[];cur=None
    for _ in range(maxpages):
        p=dict(limit=100,program="pump",chainId=CH)
        if cur: p["cursor"]=cur
        d=get(f"https://swap-api.pump.fun/v2/coins/{mint}/trades",p)
        if not d: break
        out+=d["trades"]
        if not d["pagination"]["hasMore"]: break
        cur=d["pagination"]["nextCursor"]
    return mint,out
res={}
with cf.ThreadPoolExecutor(10) as ex:
    for i,(m,t) in enumerate(ex.map(trades,cand)):
        res[m]=t
        if i%250==0: print(i,len(cand),flush=True)
json.dump(res,open("trades.json","w")); print("done",sum(map(len,res.values())),flush=True)
