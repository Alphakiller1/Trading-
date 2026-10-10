import requests, json, time, sys, concurrent.futures as cf, os
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36","Origin":"https://pump.fun","Referer":"https://pump.fun/"}
B="https://frontend-api-v3.pump.fun"; CH="solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
S=requests.Session(); S.headers.update(H)
def get(url,params,tries=4):
    for i in range(tries):
        try:
            r=S.get(url,params=params,timeout=30)
            if r.status_code==200: return r.json()
            if r.status_code in (429,500,502,503,504): time.sleep(2**i); continue
            return None
        except Exception: time.sleep(2**i)
    return None
coins={}
for sort in ("created_timestamp","last_trade_timestamp","market_cap"):
    for off in range(0,2000,50):
        d=get(f"{B}/coins",dict(offset=off,limit=50,sort=sort,order="DESC",includeNsfw="true"))
        if not d: break
        for c in d: coins.setdefault(c["mint"],c)
print("coins",len(coins),file=sys.stderr)
json.dump(coins,open("coins.json","w"))
# coins whose history includes a sub-80k phase: all pump-program coins (launch at ~$4-5k) created in last 3 days
now=time.time()*1000
cand=[c for c in coins.values() if now-c["created_timestamp"]<7*86400e3 and c.get("program")=="pump"]
print("recent coins",len(cand),file=sys.stderr)
def trades(mint,maxpages=10):
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
with cf.ThreadPoolExecutor(6) as ex:
    for i,(m,t) in enumerate(ex.map(trades,[c["mint"] for c in cand])):
        res[m]=t
        if i%100==0: print(i,file=sys.stderr)
json.dump(res,open("trades.json","w"))
print("done",sum(len(v) for v in res.values()),file=sys.stderr)
