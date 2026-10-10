"""Copy-trade backtest with cross-fitting: wallets ranked on half A coins, copied on half B coins (and vice versa).
Entry: first buy by a qualifying wallet on a coin (or confluence of N such wallets within W sec), we buy after `lat` s.
Exit: 'mirror' = sell `lat` s after the leader's first sell (with a safety stop + max hold); or own rules."""
import json, collections, statistics as st, math, sys, datetime as dt, bisect
import strategies as S, backtest as bt
def sec(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
RAW={m:sorted([t for t in v if t.get("priceUsd")],key=lambda t:t["slotIndexId"]) for m,v in json.load(open(sys.argv[1] if len(sys.argv)>1 else "trades.json")).items()}
coins=bt.coins
pos=json.load(open("positions.json"))
def ranking(h,min_n=3,min_roi=0.0,min_win=0.0,maxbuy=1000):
    acc=collections.defaultdict(lambda:[0,0.0,0.0,0,[]])
    for p in pos:
        if S.split(p["mint"])!=h or p["dev"] or p["max_buy"]>maxbuy: continue
        a=acc[p["w"]]; a[0]+=1; a[1]+=p["pnl"]; a[2]+=p["buy_usd"]; a[3]+=p["pnl"]>0; a[4].append(p["hold"])
    return {w for w,a in acc.items() if a[0]>=min_n and a[2]>0 and a[1]/a[2]>min_roi and a[3]/a[0]>=min_win and st.median(a[4])>=20}  # skip sub-20s bots
T_END=max(sec(v[-1]["timestamp"]) for v in RAW.values() if v)
def run(min_n=3,min_roi=0.0,min_win=0.0,conf=1,win=300,lat=15,size=100,exit="mirror",stop=0.30,tmax=7200,mc_hi=80000,mc_lo=0):
    out=[]
    for h in (0,1):
        smart=ranking(1-h,min_n,min_roi,min_win)
        for m,tr in RAW.items():
            if S.split(m)!=h or len(tr)<10: continue
            ts=[sec(t["timestamp"]) for t in tr]; px=[float(t["priceUsd"]) for t in tr]
            tape=list(zip(ts,px,[float(t["amountUsd"] or 0) for t in tr])); k=bt.kcoin(m)
            seen={}; trig=None
            for i,t in enumerate(tr):
                w=t["userAddress"]
                if t["type"]=="buy" and w in smart and w not in seen:
                    seen[w]=ts[i]
                    recent=[x for x in seen.values() if ts[i]-x<=win]
                    mc=px[i]*1e9
                    if len(recent)>=conf and mc_lo<=mc<=mc_hi: trig=(i,w); break
            if not trig: continue
            i,leader=trig; t_in=ts[i]+lat
            if T_END-t_in<tmax: continue
            j=bisect.bisect_left(ts,t_in)
            if j>=len(tr): continue
            pe=px[j]; tok=bt.buy(size,pe,k)
            x=(size-bt.fomo_fee(size))*0.99/bt.SOLUSD; vS=math.sqrt(pe/bt.SOLUSD*k); lift=((vS+x)/vS)**2
            # leader's first sell after our entry signal
            lsell=next((ts[n] for n in range(i+1,len(tr)) if tr[n]["userAddress"]==leader and tr[n]["type"]=="sell"),None)
            t_exit=None; why="end"; pxx=px[-1]
            for n in range(j+1,len(tr)):
                if ts[n]-t_in<lat: continue
                if px[n]<=pe*(1-stop): why="stop"; pxx=px[n]; break
                if exit=="mirror" and lsell and ts[n]>=lsell+lat: why="mirror"; pxx=px[n]; break
                if ts[n]-t_in>tmax: why="time"; pxx=px[n]; break
            got=bt.sell(tok,pxx*lift,k)
            out.append(dict(m=m,pnl=got-size,ret=pxx/pe-1,why=why,mc=pe*1e9,lat=lat))
    return out
def rep(r,size):
    if len(r)<10: return f"n={len(r)}"
    pn=sorted([x["pnl"] for x in r],reverse=True); top=max(1,len(pn)//50)
    return f"n={len(r):4d} win%={100*sum(p>0 for p in pn)/len(pn):3.0f} roi={100*sum(pn)/size/len(pn):+6.1f}% med={100*st.median(pn)/size:+6.1f}% roi_ex_top2%={100*sum(pn[top:])/size/len(pn):+6.1f}% exits={dict(collections.Counter(x['why'] for x in r))}"
if __name__=="__main__":
    for cfg in [dict(),dict(min_roi=0.25,min_win=0.5),dict(conf=2),dict(min_roi=0.25,min_win=0.5,conf=2),dict(min_n=5,min_roi=0.25)]:
        for lat in (5,15,30):
            for size in (100,250):
                r=run(lat=lat,size=size,**cfg); print(cfg,"lat",lat,"$",size,rep(r,size),flush=True)
