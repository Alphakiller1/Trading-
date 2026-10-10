"""Overreaction study: sharp drops caused by one dominant seller (dev/sniper dump) vs broad selling.
Buy the dip after human latency; exit on partial rebound / stop / time. Costs included."""
import json, sys, math, bisect, collections, statistics as st, datetime as dt
import strategies as S, backtest as bt
def sec(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
RAW={m:sorted([t for t in v if t.get("priceUsd")],key=lambda t:t["slotIndexId"]) for m,v in json.load(open(sys.argv[1])).items()}
T_END=max(sec(v[-1]["timestamp"]) for v in RAW.values() if v)
coins=bt.coins
def events(drop=0.25,win=30,dom=0.7,min_buyers=8,mc_lo=5000,mc_hi=200000):
    ev=[]
    for m,tr in RAW.items():
        if len(tr)<50: continue
        ts=[sec(t["timestamp"]) for t in tr]; px=[float(t["priceUsd"]) for t in tr]
        creator=coins.get(m,{}).get("creator"); last=-1e18
        for i in range(1,len(tr)):
            if ts[i]-last<600: continue
            lo=bisect.bisect_left(ts,ts[i]-win)
            peak=max(px[lo:i+1]); 
            if px[i]>peak*(1-drop): continue
            mc=px[i]*1e9
            if not (mc_lo<=mc<=mc_hi): continue
            sells=collections.Counter(); tot=0.0
            for j in range(lo,i+1):
                if tr[j]["type"]=="sell":
                    u=float(tr[j]["amountUsd"] or 0); sells[tr[j]["userAddress"]]+=u; tot+=u
            if tot<=0: continue
            w,top=sells.most_common(1)[0]
            b5=bisect.bisect_left(ts,ts[i]-300)
            buyers={tr[j]["userAddress"] for j in range(b5,lo) if tr[j]["type"]=="buy"}
            ev.append(dict(m=m,t=ts[i],i=i,mc=mc,dom=top/tot,dev=int(w==creator),buyers=len(buyers),
                           peak=peak,px=px[i],age=(ts[i]-coins.get(m,{}).get("created_timestamp",0)/1000)/60,hour=dt.datetime.utcfromtimestamp(ts[i]).hour))
            last=ts[i]
    return ev
def trade(e,size=100,lat=10,tgt=0.5,stop=0.20,tmax=600):
    """tgt = fraction of the drop to recover (0.5 = halfway back to the pre-dump peak)"""
    m=e["m"]; tape=S.TAPES.get(m); k=bt.kcoin(m)
    if not tape or T_END-e["t"]<tmax+lat: return None
    j=S.first_idx(tape,e["t"]+lat)
    if j is None: return None
    pe=tape[j][1]; target=pe+(e["peak"]-pe)*tgt
    tok=bt.buy(size,pe,k); x=(size-bt.fomo_fee(size))*0.99/bt.SOLUSD; vS=math.sqrt(pe/bt.SOLUSD*k); lift=((vS+x)/vS)**2
    why="end"; pxx=tape[-1][1]
    for t,p,u in tape[j+1:]:
        if t-tape[j][0]<lat: continue
        if p>=target: why="target"; pxx=p; break
        if p<=pe*(1-stop): why="stop"; pxx=p; break
        if t-tape[j][0]>tmax: why="time"; pxx=p; break
    return dict(pnl=bt.sell(tok,pxx*lift,k)-size,why=why,ret=pxx/pe-1)
def rep(name,ev,**kw):
    r=[x for x in (trade(e,**kw) for e in ev) if x]
    if len(r)<10: print(f"{name:40s} n={len(r)}"); return
    pn=sorted([x["pnl"] for x in r],reverse=True); s=kw.get("size",100); top=max(1,len(pn)//50)
    print(f"{name:40s} n={len(r):4d} win%={100*sum(p>0 for p in pn)/len(pn):3.0f} roi={100*sum(pn)/s/len(pn):+6.1f}% med={100*st.median(pn)/s:+6.1f}% ex_top2%={100*sum(pn[top:])/s/len(pn):+6.1f}% {dict(collections.Counter(x['why'] for x in r))}")
if __name__=="__main__":
    for drop in (0.2,0.3,0.4):
        ev=events(drop=drop)
        print(f"--- drop>={int(drop*100)}% in 30s: {len(ev)} events")
        rep(" all",ev)
        rep(" one dominant seller (>=70%)",[e for e in ev if e["dom"]>=0.7])
        rep(" dominant seller + >=8 recent buyers",[e for e in ev if e["dom"]>=0.7 and e["buyers"]>=8])
        rep(" dev dump",[e for e in ev if e["dev"]])
        rep(" broad selling (<50% one seller)",[e for e in ev if e["dom"]<0.5])
        rep(" dominant+buyers, $250",[e for e in ev if e["dom"]>=0.7 and e["buyers"]>=8],size=250)
        rep(" dominant+buyers, tgt 30%",[e for e in ev if e["dom"]>=0.7 and e["buyers"]>=8],tgt=0.3)
        rep(" dominant+buyers, lat 20s",[e for e in ev if e["dom"]>=0.7 and e["buyers"]>=8],lat=20)
