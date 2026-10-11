"""Rebuild the price path after each recent callout from the trade tape, then simulate stop/take-profit exits.
Caller record uses only that caller's calls made >=24h before the call (no look-ahead)."""
import json, time, requests, statistics as st, collections, math, sys
import datetime as dt
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36","Origin":"https://pump.fun","Referer":"https://pump.fun/"}
CH="solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"; S=requests.Session(); S.headers.update(H)
def sec(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
def get(u,p):
    for i in range(3):
        try:
            r=S.get(u,params=p,timeout=10)
            if r.ok: return r.json()
            if r.status_code==429: time.sleep(4*(i+1)); continue
            return None
        except Exception: time.sleep(2)
data=json.load(open("callouts.json")); now=time.time()*1000
calls=[]
for w,cs in data.items():
    cs=sorted([c for c in cs if c.get("marketCap") and c.get("chain") in (None,"solana") and not c.get("perp")],key=lambda c:c["createdAt"])
    for k,c in enumerate(cs):
        if not (c["coinMint"].endswith("pump") and c["marketCap"]<200000 and 26*3600e3<=now-c["createdAt"]<=4*86400e3): continue
        prior=[p for p in cs[:k] if c["createdAt"]-p["createdAt"]>=24*3600e3 and p.get("maxMultiplier")]
        calls.append(dict(w=w,m=c["coinMint"],t=c["createdAt"]/1000,mc=c["marketCap"],n_prior=len(prior),
                          prior_hit2=(sum(p["maxMultiplier"]>=2 for p in prior)/len(prior)) if prior else None))
import random; random.seed(7)
_good=[c for c in calls if c["n_prior"]>=5 and c["prior_hit2"]>=0.3]; _rest=[c for c in calls if c not in _good]
calls=_good+random.sample(_rest,min(120,len(_rest)))
print("recent callouts to rebuild:",len(calls),"unique coins:",len({c['m'] for c in calls}),flush=True)
paths={}
if "--fetch" in sys.argv:
    for i,c in enumerate(calls):
        if c["m"] in paths: continue
        out=[];cur=None;ok=False
        for _ in range(40):
            p=dict(limit=100,program="pump",chainId=CH)
            if cur: p["cursor"]=cur
            d=get(f"https://swap-api.pump.fun/v2/coins/{c['m']}/trades",p)
            if not d: break
            out+=[(sec(t["timestamp"]),float(t["priceUsd"])) for t in d["trades"] if t.get("priceUsd")]
            if out and out[-1][0]<=min(x["t"] for x in calls if x["m"]==c["m"]): ok=True; break
            if not d["pagination"]["hasMore"]: ok=True; break
            cur=d["pagination"]["nextCursor"]
        if ok: paths[c["m"]]=sorted(out)
        if i%25==0: print(i,len(paths),flush=True); json.dump(paths,open("callout_paths.json","w"))
    json.dump(paths,open("callout_paths.json","w")); print("paths:",len(paths)); sys.exit()
paths=json.load(open("callout_paths.json"))
SOL=110.0; K=20.27*1.066e9
def fee(u): return 0.10 if u<5 else u*0.02 if u<47.5 else 0.95 if u<190 else u*0.005
def trade(c,size=100,lat=30,stop=0.3,tp=2.0,tmax=86400):
    path=paths.get(c["m"])
    if not path: return None
    after=[(t,p) for t,p in path if t>=c["t"]+lat]
    if not after: return None
    pe=after[0][1]; x=None
    for t,p in after[1:]:
        if p<=pe*(1-stop) or p>=pe*tp or t-after[0][0]>tmax: x=p; break
    x=x if x is not None else after[-1][1]
    if after[-1][0]-after[0][0]<tmax and x==after[-1][1] and time.time()-after[-1][0]<3600: return None   # still open: skip
    gross=x/pe; slip=1-min(0.02,size/ (pe*1e9/10))  # rough slippage haircut, tiny at these sizes
    return size*gross*slip*0.98-fee(size)-fee(size*gross)-size
def rep(name,cs,**kw):
    r=[(c,v) for c in cs for v in [trade(c,**kw)] if v is not None]
    if len(r)<8: print(f" {name:46s} n={len(r)}"); return
    r.sort(key=lambda z:z[0]["t"]); p=[v/kw.get("size",100) for _,v in r]; h=len(p)//2
    print(f" {name:46s} n={len(p):3d} avg {100*st.mean(p):+6.1f}% median {100*st.median(p):+6.1f}% win {100*sum(v>0 for v in p)/len(p):3.0f}% | earlier {100*st.mean(p[:h]):+6.1f}% later {100*st.mean(p[h:]):+6.1f}%")
print("callouts with rebuilt paths:",sum(1 for c in calls if c["m"] in paths))
good=[c for c in calls if c["n_prior"]>=5 and c["prior_hit2"]>=0.3]
great=[c for c in calls if c["n_prior"]>=5 and c["prior_hit2"]>=0.5]
for lat in (30,120):
    print(f"\n== entry {lat}s after the call, $100, stop -30%, take profit 2x, max 24h ==")
    rep("all recent calls < $200k",calls,lat=lat); rep("callers >=5 prior, 2x-rate >= 30%",good,lat=lat); rep("callers >=5 prior, 2x-rate >= 50%",great,lat=lat)
print("\n== exit variants, callers 2x-rate >= 30%, entry 30s ==")
for stop,tp in ((0.2,1.5),(0.3,1.5),(0.4,2.0),(0.5,3.0),(0.3,3.0)):
    rep(f"stop -{int(stop*100)}%, tp {tp}x",good,stop=stop,tp=tp)
