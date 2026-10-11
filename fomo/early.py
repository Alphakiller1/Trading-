"""Early-entry study: buy at launch + d seconds using only info known at that moment. Walk-forward by launch time."""
import json, math, collections, statistics as st, datetime as dt, bisect, itertools
SOL=110.0; K=20.27*1.066e9
def fee(u): return 0.10 if u<5 else u*0.02 if u<47.5 else 0.95 if u<190 else u*0.005
def buy(u,p):
    x=(u-fee(u))*0.99/SOL; vS=math.sqrt(p/SOL*K); vT=K/vS; return vT-K/(vS+x), ((vS+x)/vS)**2
def sell(tok,p):
    vS=math.sqrt(p/SOL*K); vT=K/vS; u=(vS-K/(vT+tok))*SOL*0.99; return u-fee(u)
def sec(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
# ---- load complete launch tapes ----
L=[]
for l in open("live/coins.jsonl"):
    d=json.loads(l); tr=sorted([t for t in d["trades"] if t.get("priceUsd")],key=lambda t:t["slotIndexId"])
    if tr: L.append(dict(c=d["coin"],tr=tr,src="live",horizon=1800))
coins=json.load(open("coins.json")); T=json.load(open("trades_v1.json"))
tend=max(sec(v[0]["timestamp"]) for v in T.values() if v)
for m,v in T.items():
    c=coins.get(m,{}); t0=c.get("created_timestamp",0)/1000
    if not v or len(v)>=1000 or not t0: continue
    tr=sorted([t for t in v if t.get("priceUsd")],key=lambda t:t["slotIndexId"])
    if tr and sec(tr[0]["timestamp"])-t0<20: L.append(dict(c={k:c.get(k) for k in ("mint","creator","created_timestamp","twitter","telegram","website","description","name","symbol")},tr=tr,src="hist",horizon=min(1800,tend-t0)))
L=[x for x in L if x["horizon"]>=1200]
L.sort(key=lambda x:x["c"]["created_timestamp"])
# ---- creator history, past-only (from all coin metadata we have) ----
allc=sorted([c for c in coins.values() if c.get("creator")],key=lambda c:c["created_timestamp"])
for x in L:
    cr=x["c"]["creator"]; t0=x["c"]["created_timestamp"]
    prev=[c for c in allc if c["creator"]==cr and c["created_timestamp"]<t0-3600*1000]
    x["dev_prev"]=len(prev); x["dev_prev_best"]=max([c.get("ath_market_cap") or 0 for c in prev] or [0])
print("launches with complete tapes:",len(L),collections.Counter(x["src"] for x in L))
def feats(x,d):
    c=x["c"]; tr=x["tr"]; t0=c["created_timestamp"]/1000
    early=[t for t in tr if sec(t["timestamp"])-t0<=d]
    dev_buy=sum(float(t["amountUsd"] or 0) for t in early if t["userAddress"]==c["creator"] and t["type"]=="buy")
    devsold=any(t["userAddress"]==c["creator"] and t["type"]=="sell" for t in early)
    eb=collections.Counter()
    for t in early:
        if t["type"]=="buy" and t["userAddress"]!=c["creator"]: eb[t["userAddress"]]+=float(t["amountUsd"] or 0)
    tot=sum(eb.values()); conc=sum(v for _,v in eb.most_common(3))/tot if tot else None
    tw=(c.get("twitter") or "").lower()
    return dict(dev_buy=dev_buy,devsold=devsold,conc=conc,nbuyers=len(eb),buyvol=tot,
                social="web/tg" if (c.get("website") or c.get("telegram")) else "x_profile" if tw and "/status/" not in tw else "tweet" if tw else "none",
                desc=len(c.get("description") or ""),dev_prev=x["dev_prev"],dev_prev_best=x["dev_prev_best"])
def sim(x,d,lat=3,size=100,stop=0.3,tp=1.0,tmax=1200):
    c=x["c"]; tr=x["tr"]; t0=c["created_timestamp"]/1000
    ts=[sec(t["timestamp"]) for t in tr]; px=[float(t["priceUsd"]) for t in tr]
    j=bisect.bisect_left(ts,t0+d+lat)
    if j>=len(ts): return dict(pnl=-size*0.06,why="no_trades_after")   # coin dead before we could enter: we wouldn't buy; tiny cost proxy
    pe=px[j]; tok,lift=buy(size,pe); left=tok; got=0; half=False; why="time"; pxx=px[-1]; hi=pe
    for i in range(j+1,len(tr)):
        p=px[i]; hi=max(hi,p)
        if not half and p>=pe*(1+tp): got+=sell(left*0.5,p*lift); left*=0.5; half=True; hi=p
        if not half and p<=pe*(1-stop): why="stop"; pxx=p; break
        if half and p<=hi*0.7: why="trail"; pxx=p; break
        if ts[i]-ts[j]>tmax: why="time"; pxx=p; break
    got+=sell(left,pxx*lift)
    return dict(pnl=got-size,why=why,entry_mc=pe*1e9)
def rep(rows,size=100):
    if len(rows)<5: return f"n={len(rows)}"
    pn=sorted([r["pnl"] for r in rows],reverse=True); top=max(1,len(pn)//50); h=len(rows)//2
    first=[r["pnl"] for r in rows[:h]]; second=[r["pnl"] for r in rows[h:]]
    return (f"n={len(pn):4d} roi={100*sum(pn)/size/len(pn):+6.1f}% win={100*sum(p>0 for p in pn)/len(pn):3.0f}% "
            f"ex_top2%={100*sum(pn[top:])/size/len(pn):+6.1f}% | earlier half {100*sum(first)/size/max(len(first),1):+6.1f}% later half {100*sum(second)/size/max(len(second),1):+6.1f}%")
if __name__=="__main__":
    print("\n== entry delay, ALL launches (with 3s execution latency) ==")
    for d in (3,10,30,60):
        rows=[dict(sim(x,d),**feats(x,d)) for x in L]
        print(f" buy at launch+{d:>2}s: {rep(rows)}")
    d=10
    rows=[dict(sim(x,d),**feats(x,d),t=x["c"]["created_timestamp"]) for x in L]
    print(f"\n== conditioning at launch+{d}s (rows in launch-time order; 'later half' = out-of-time check) ==")
    groups=[("socials web/tg",lambda r:r["social"]=="web/tg"),("socials x_profile",lambda r:r["social"]=="x_profile"),("socials tweet",lambda r:r["social"]=="tweet"),("no socials",lambda r:r["social"]=="none"),
            ("dev buy >= $100",lambda r:r["dev_buy"]>=100),("dev buy < $20",lambda r:r["dev_buy"]<20),("dev sold already",lambda r:r["devsold"]),
            ("dev: first known launch",lambda r:r["dev_prev"]==0),("dev: 1-5 prior launches",lambda r:1<=r["dev_prev"]<=5),("dev: >5 prior (serial)",lambda r:r["dev_prev"]>5),
            ("dev had prior coin >= $50k",lambda r:r["dev_prev_best"]>=5e4),
            ("early buyers >= 5",lambda r:r["nbuyers"]>=5),("early conc <= 60%",lambda r:r["conc"] is not None and r["conc"]<=0.6),("early conc > 80%",lambda r:r["conc"] is not None and r["conc"]>0.8),
            ("description >= 50 chars",lambda r:r["desc"]>=50)]
    for name,f in groups:
        print(f" {name:28s} {rep([r for r in rows if f(r)])}")
