"""Early-quality-launch strategy: at launch+W s, if buyers>=B, top-3 early-buy share<=C, dev hasn't sold -> buy (after latency).
Exits: stop / take-profit half / time. Costs: fomo tiers + 1% pump + bonding-curve slippage (own-impact lift)."""
import json, math, collections, statistics as st, datetime as dt, itertools, hashlib, sys
SOL=110.0; K=20.27*1.066e9
def fee(u): return 0.10 if u<5 else u*0.02 if u<47.5 else 0.95 if u<190 else u*0.005
def buy(u,p):
    x=(u-fee(u))*0.99/SOL; vS=math.sqrt(p/SOL*K); vT=K/vS; return vT-K/(vS+x), ((vS+x)/vS)**2
def sell(tok,p):
    vS=math.sqrt(p/SOL*K); vT=K/vS; u=(vS-K/(vT+tok))*SOL*0.99; return u-fee(u)
def sec(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
def load():
    C=[]
    for l in open("live/coins.jsonl"):
        d=json.loads(l); tr=sorted([t for t in d["trades"] if t.get("priceUsd")],key=lambda t:t["slotIndexId"])
        if tr: C.append((d["coin"]["mint"],d["coin"]["creator"],d["coin"]["created_timestamp"]/1000,tr,"live"))
    coins=json.load(open("coins.json")); T=json.load(open("trades_v1.json"))
    tend=max(sec(v[0]["timestamp"]) for v in T.values() if v)
    for m,v in T.items():
        c=coins.get(m,{}); t0=c.get("created_timestamp",0)/1000
        if not v or len(v)>=1000 or not t0 or tend-t0<1800: continue      # need complete tape and >=30 min of life
        tr=sorted([t for t in v if t.get("priceUsd")],key=lambda t:t["slotIndexId"])
        if tr and sec(tr[0]["timestamp"])-t0<30: C.append((m,c.get("creator"),t0,tr,"hist"))
    return C
COINS=load()
def run(W=60,B=15,Cc=0.6,lat=10,size=20,stop=0.35,tp=1.0,tp_frac=0.5,tmax=1200):
    out=[]
    for m,creator,t0,tr,src in COINS:
        ts=[sec(t["timestamp"]) for t in tr]; px=[float(t["priceUsd"]) for t in tr]
        early=[i for i in range(len(tr)) if ts[i]-t0<=W]
        if not early: continue
        buyers={tr[i]["userAddress"] for i in early if tr[i]["type"]=="buy"}
        if len(buyers)<B: continue
        if any(tr[i]["userAddress"]==creator and tr[i]["type"]=="sell" for i in early): continue
        eb=collections.Counter()
        for i in early:
            if tr[i]["type"]=="buy": eb[tr[i]["userAddress"]]+=float(tr[i]["amountUsd"] or 0)
        tot=sum(eb.values())
        if not tot or sum(v for _,v in eb.most_common(3))/tot>Cc: continue
        tin=t0+W+lat; j=next((i for i in range(len(tr)) if ts[i]>=tin),None)
        if j is None or px[j]*1e9>200000: continue
        pe=px[j]; tok,lift=buy(size,pe); left=tok; got=0; why="time"; pxx=px[-1]; done=False
        for i in range(j+1,len(tr)):
            p=px[i]
            if not done and tp and p>=pe*(1+tp): got+=sell(left*tp_frac,p*lift); left*=1-tp_frac; done=True
            if p<=pe*(1-stop) and not done: why="stop"; pxx=p; break
            if done and p<=pe: why="be"; pxx=p; break
            if ts[i]-tin>tmax: why="time"; pxx=p; break
        got+=sell(left,pxx*lift)
        out.append(dict(m=m,src=src,pnl=got-size,why=why,h=int(hashlib.md5(m.encode()).hexdigest(),16)%2))
    return out
def rep(r,size=20):
    if not r: return "n=0"
    pn=sorted([x["pnl"] for x in r],reverse=True); top=max(1,len(pn)//50)
    f=lambda rr: f"{100*sum(x['pnl'] for x in rr)/size/len(rr):+6.1f}% (n={len(rr)})" if rr else "n=0"
    return (f"n={len(r):3d} roi={100*sum(pn)/size/len(pn):+6.1f}% win%={100*sum(p>0 for p in pn)/len(pn):3.0f} ex_top2%={100*sum(pn[top:])/size/len(pn):+6.1f}% "
            f"| A {f([x for x in r if x['h']==0])} B {f([x for x in r if x['h']==1])} | live {f([x for x in r if x['src']=='live'])} hist {f([x for x in r if x['src']=='hist'])}")
if __name__=="__main__":
    print("coins usable:",len(COINS),collections.Counter(c[4] for c in COINS))
    print("baseline: any coin, enter at 70s:", rep(run(B=0,Cc=1.01)))
    for W,B,Cc in itertools.product((60,120),(10,20,40),(0.4,0.6)):
        print(f"W={W}s buyers>={B} conc<={Cc}:", rep(run(W=W,B=B,Cc=Cc)),flush=True)
