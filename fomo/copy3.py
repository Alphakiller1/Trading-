"""Copy-trade model v2: richer leader/coin filters + exit variants, results per coin-half for robustness."""
import json, collections, statistics as st, math, sys, datetime as dt, bisect
import strategies as S, backtest as bt
def sec(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
RAW={m:sorted([t for t in v if t.get("priceUsd")],key=lambda t:t["slotIndexId"]) for m,v in json.load(open("trades_v1.json")).items()}
coins=bt.coins; pos=json.load(open("positions.json"))
T_END=max(sec(v[-1]["timestamp"]) for v in RAW.values() if v)
coin_freq=collections.Counter(p["w"] for p in pos)
def ranking(h,min_n,max_n,min_roi,min_win,min_hold=20):
    acc=collections.defaultdict(lambda:[0,0.0,0.0,0,[]])
    for p in pos:
        if S.split(p["mint"])!=h or p["dev"] or p["max_buy"]>1000: continue
        a=acc[p["w"]]; a[0]+=1; a[1]+=p["pnl"]; a[2]+=p["buy_usd"]; a[3]+=p["pnl"]>0; a[4].append(p["hold"])
    return {w:a[1]/a[2] for w,a in acc.items() if min_n<=a[0]<=max_n and a[2]>0 and a[1]/a[2]>min_roi and a[3]/a[0]>=min_win and st.median(a[4])>=min_hold}
PRE={}
def prep():
    for m,tr in RAW.items():
        if len(tr)<10: continue
        PRE[m]=dict(ts=[sec(t["timestamp"]) for t in tr],px=[float(t["priceUsd"]) for t in tr],
                    usd=[float(t["amountUsd"] or 0) for t in tr],side=[t["type"] for t in tr],who=[t["userAddress"] for t in tr],k=bt.kcoin(m),
                    t0=coins.get(m,{}).get("created_timestamp",0)/1000,creator=coins.get(m,{}).get("creator"))
prep()
SK={}
def run(min_hold=20,early_conc=None,min_n=3,max_n=1000,min_roi=0.0,min_win=0.0,min_lbuy=0,min_age=0,nodev=False,min_net=None,min_buyers=0,
        lat=15,size=100,stop=0.30,tmax=7200,mirror=True,tp1=None,tp1_frac=0.5,trail=None,mc_lo=0,mc_hi=80000,hours=None):
    out=[]
    for h in (0,1):
        key=(h,min_n,max_n,min_roi,min_win,min_hold)
        if key not in SK: SK[key]=ranking(1-h,min_n,max_n,min_roi,min_win,min_hold)
        smart=SK[key]
        for m,P in PRE.items():
            if S.split(m)!=h: continue
            ts,px,usd,side,who=P["ts"],P["px"],P["usd"],P["side"],P["who"]
            if early_conc is not None:
                eb=collections.Counter()
                for q in range(min(30,len(ts))):
                    if side[q]=="buy": eb[who[q]]+=usd[q]
                tot=sum(eb.values())
                if tot>0 and sum(v for _,v in eb.most_common(3))/tot>early_conc: continue
            seen=set(); trig=None; devsold=False
            for i in range(len(ts)):
                if who[i]==P["creator"] and side[i]=="sell": devsold=True
                if side[i]!="buy": continue
                w=who[i]
                if w in smart and w not in seen:
                    seen.add(w)
                    mc=px[i]*1e9
                    if not (mc_lo<=mc<=mc_hi) or usd[i]<min_lbuy: continue
                    if P["t0"] and ts[i]-P["t0"]<min_age: continue
                    if nodev and devsold: continue
                    if hours is not None and dt.datetime.utcfromtimestamp(ts[i]).hour not in hours: continue
                    lo=bisect.bisect_left(ts,ts[i]-300)
                    if min_net is not None:
                        net=sum(usd[j]*(1 if side[j]=="buy" else -1) for j in range(lo,i))
                        if net<min_net: continue
                    if min_buyers and len({who[j] for j in range(lo,i) if side[j]=="buy"})<min_buyers: continue
                    trig=(i,w); break
                seen.add(w)
            if not trig: continue
            i,leader=trig; t_in=ts[i]+lat
            if T_END-t_in<tmax: continue
            j=bisect.bisect_left(ts,t_in)
            if j>=len(ts): continue
            k=P["k"]; pe=px[j]; tok=bt.buy(size,pe,k); left=tok; got=0.0
            x=(size-bt.fomo_fee(size))*0.99/bt.SOLUSD; vS=math.sqrt(pe/bt.SOLUSD*k); lift=((vS+x)/vS)**2
            lsell=next((ts[n] for n in range(i+1,len(ts)) if who[n]==leader and side[n]=="sell"),None)
            why="end"; pxx=px[-1]; hi=pe; tp_done=False
            for n in range(j+1,len(ts)):
                if ts[n]-t_in<lat: continue
                p=px[n]; hi=max(hi,p)
                if tp1 and not tp_done and p>=pe*(1+tp1):
                    part=left*tp1_frac; got+=bt.sell(part,p*lift,k); left-=part; tp_done=True
                if p<=pe*(1-stop) and not tp_done: why="stop"; pxx=p; break
                if tp_done and p<=pe: why="be"; pxx=p; break          # breakeven stop after scale-out
                if trail and hi>=pe*1.2 and p<=hi*(1-trail): why="trail"; pxx=p; break
                if mirror and lsell and ts[n]>=lsell+lat: why="mirror"; pxx=p; break
                if ts[n]-t_in>tmax: why="time"; pxx=p; break
            got+=bt.sell(left,pxx*lift,k)
            out.append(dict(h=h,m=m,pnl=got-size,why=why))
    return out
def rep(r,size=100):
    def one(rr):
        if len(rr)<8: return f"n={len(rr):3d}        "
        return f"n={len(rr):3d} roi={100*sum(x['pnl'] for x in rr)/size/len(rr):+6.1f}%"
    pn=sorted([x["pnl"] for x in r],reverse=True); top=max(1,len(pn)//50)
    ex=100*sum(pn[top:])/size/max(len(pn),1)
    win=100*sum(p>0 for p in pn)/max(len(pn),1)
    return f"ALL {one(r)} win%={win:3.0f} ex_top2%={ex:+6.1f}% | A {one([x for x in r if x['h']==0])} | B {one([x for x in r if x['h']==1])}"
if __name__=="__main__":
    tests=[("baseline",{}),("leader median hold >= 60s",dict(min_hold=60)),("hold >= 180s",dict(min_hold=180)),
           ("hold >= 300s",dict(min_hold=300)),("hold >= 900s",dict(min_hold=900)),("hold >= 1800s",dict(min_hold=1800)),
           ("hold>=300 + dev not sold",dict(min_hold=300,nodev=True)),("hold>=300 + $250",dict(min_hold=300,size=250)),
           ("hold>=300 + lat 30s",dict(min_hold=300,lat=30)),("hold>=300 + lat 60s",dict(min_hold=300,lat=60)),
           ("early top3 conc <= 60%",dict(early_conc=0.6)),("early top3 conc <= 40%",dict(early_conc=0.4)),
           ("hold>=300 + conc<=60%",dict(min_hold=300,early_conc=0.6)),("hold>=300 + conc<=60% + nodev",dict(min_hold=300,early_conc=0.6,nodev=True))]
    for name,kw in tests:
        r=run(**kw); print(f"{name:34s} {rep(r,kw.get('size',100))}",flush=True)
