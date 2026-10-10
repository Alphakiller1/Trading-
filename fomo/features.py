"""Event study: snapshot each active coin once per minute, compute point-in-time features,
label with after-cost trade outcome. Smart-wallet features are cross-fitted (skill learned on
the other half of coins) so there is no leakage."""
import json, math, collections, statistics as st, bisect
import pandas as pd
import strategies as S, backtest as bt
coins=bt.coins
RAW={m:sorted([t for t in v if t.get("priceUsd")],key=lambda t:t["slotIndexId"]) for m,v in json.load(open("trades.json")).items()}
pos=json.load(open("positions.json"))
T_END=max(S.sec(t["timestamp"]) for v in RAW.values() for t in v[-1:]) if hasattr(S,"sec") else None
import datetime as dt
def sec(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
T_END=max(sec(v[-1]["timestamp"]) for v in RAW.values() if v)
# ---- cross-fitted wallet skill ----
skill={0:{},1:{}}   # skill[h][w] learned on coins of half h
for h in (0,1):
    acc=collections.defaultdict(lambda:[0,0.0,0.0,0])
    for p in pos:
        if S.split(p["mint"])!=h or p["dev"]: continue
        a=acc[p["w"]]; a[0]+=1; a[1]+=p["pnl"]; a[2]+=p["buy_usd"]; a[3]+=p["pnl"]>0
    for w,(n,pnl,b,wins) in acc.items():
        if n>=3 and b>0 and pnl/b>0.25 and wins/n>=0.5: skill[h][w]=1      # "smart"
        elif n>=3 and b>0 and pnl/b<-0.25: skill[h][w]=-1                  # "dumb money"
print("smart wallets per half",[sum(v==1 for v in skill[h].values()) for h in (0,1)])
EXITS={"quick":dict(lat=10,stop=0.15,tp1=0.30,tp1_frac=0.5,trail=0.20,tmax=900),
       "swing":dict(lat=10,stop=0.25,tp1=0.50,tp1_frac=0.5,trail=0.30,tmax=7200)}
rows=[]
for m,tr in RAW.items():
    if len(tr)<30: continue
    h=S.split(m); sk=skill[1-h]; c=coins.get(m,{}); t0=c.get("created_timestamp",0)/1000; creator=c.get("creator")
    trunc=len(tr)>=1000
    ts=[sec(t["timestamp"]) for t in tr]; px=[float(t["priceUsd"]) for t in tr]
    usd=[float(t["amountUsd"] or 0) for t in tr]; side=[t["type"] for t in tr]; who=[t["userAddress"] for t in tr]
    tape=S.TAPES.get(m) or [(a,b,c_) for a,b,c_ in zip(ts,px,usd)]
    k=bt.kcoin(m); ath=0; devsold=False; i=0; last_ev=-1e18
    for g in range(int(ts[0]//60)+1,int(ts[-1]//60)+1):
        t=g*60.0
        while i<len(tr) and ts[i]<=t:
            ath=max(ath,px[i]); devsold|=(who[i]==creator and side[i]=="sell"); i+=1
        if i==0: continue
        mc=px[i-1]*1e9
        if not (4000<=mc<=1_000_000): continue
        if trunc and t-ts[0]<900: continue
        if T_END-t<EXITS["swing"]["tmax"]: continue
        if t-last_ev<300: continue
        lo1=bisect.bisect_left(ts,t-60); lo5=bisect.bisect_left(ts,t-300); lo15=bisect.bisect_left(ts,t-900)
        n1=i-lo1
        if n1<3: continue
        w5=range(lo5,i)
        b5=sum(usd[j] for j in w5 if side[j]=="buy"); s5=sum(usd[j] for j in w5 if side[j]=="sell")
        b1=sum(usd[j] for j in range(lo1,i) if side[j]=="buy"); s1=sum(usd[j] for j in range(lo1,i) if side[j]=="sell")
        buyers5={who[j] for j in w5 if side[j]=="buy"}; sellers5={who[j] for j in w5 if side[j]=="sell"}
        smart5=sum(1 for w in buyers5 if sk.get(w)==1); dumb5=sum(1 for w in buyers5 if sk.get(w)==-1)
        smart_sell5=sum(1 for w in sellers5 if sk.get(w)==1)
        big=max([usd[j] for j in w5 if side[j]=="buy"] or [0])
        p1=px[lo1-1] if lo1>0 else px[0]; p5=px[lo5-1] if lo5>0 else px[0]; p15=px[lo15-1] if lo15>0 else px[0]
        f=dict(mint=m,half=h,t=t,mc=mc,age_min=(t-t0)/60 if t0 else None,n1=n1,n5=i-lo5,
               buy5=b5,sell5=s5,net5=b5-s5,net1=b1-s1,buyshare5=b5/max(b5+s5,1e-9),
               ubuy5=len(buyers5),usell5=len(sellers5),smart5=smart5,dumb5=dumb5,smart_sell5=smart_sell5,
               bigbuy_share=big/max(b5,1e-9),r1=px[i-1]/p1-1,r5=px[i-1]/p5-1,r15=px[i-1]/p15-1,
               dd_ath=px[i-1]/ath-1,devsold=int(devsold),graduated=int(tr[i-1]["program"]!="pump"),trunc=int(trunc))
        for en,X in EXITS.items():
            for size in (100,250):
                r=S.simulate(m,tape,t,size,X,k)
                f[f"{en}_{size}"]=r["pnl"]/size if r else None
        rows.append(f); last_ev=t
df=pd.DataFrame(rows); df.to_parquet("events.parquet") if False else df.to_csv("events.csv",index=False)
print("events",len(df),"coins",df.mint.nunique())
print(df[[c for c in df.columns if c.startswith(("quick","swing"))]].describe().T[["mean","50%"]])
