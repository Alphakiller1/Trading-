"""Walk-forward test of the copy strategy: wallet skill uses ONLY trades before cutoff T (open positions marked at T),
signals are traded only after T. This removes the look-ahead that coin-half splits allow."""
import collections, statistics as st, math, bisect, datetime as dt, sys
import copy4 as C, backtest as bt
PRE=C.PRE
def skill_before(T,min_n=3,maxbuy=1000):
    acc=collections.defaultdict(lambda:[0,0.0,0.0,[]])
    for m,P in PRE.items():
        ts,px,usd,side,who=P["ts"],P["px"],P["usd"],P["side"],P["who"]
        k=bisect.bisect_left(ts,T)
        if k<2: continue
        pT=px[k-1]
        pos=collections.defaultdict(lambda:[0.0,0.0,0.0,0.0,None,None,0.0])  # buy$,sell$,buytok,selltok,t_first,t_last,maxbuy
        for i in range(k):
            w=who[i]; q=pos[w]; tok=usd[i]/px[i] if px[i] else 0
            if side[i]=="buy": q[0]+=usd[i]; q[2]+=tok; q[6]=max(q[6],usd[i]); q[4]=q[4] if q[4] is not None else ts[i]
            else: q[1]+=usd[i]; q[3]+=tok
            q[5]=ts[i]
        for w,q in pos.items():
            if q[0]<=0 or w==P["creator"] or q[6]>maxbuy: continue
            mtm=max(q[2]-q[3],0)*pT
            a=acc[w]; a[0]+=1; a[1]+=q[1]+mtm-q[0]; a[2]+=q[0]; a[3].append((q[5]-q[4]) if q[4] else 0)
    return {w for w,a in acc.items() if a[0]>=min_n and a[2]>0 and a[1]/a[2]>0 and st.median(a[3])>=20}
def trade_after(T,smart,size=100,lat=15,stop=0.3,tmax=3600,conc_max=0.6,nodev=True,T_end=None,mc_hi=200000,full_only=True):
    out=[]
    for m,P in PRE.items():
        if full_only and len(P["ts"])>=1000: continue
        ts,px,usd,side,who=P["ts"],P["px"],P["usd"],P["side"],P["who"]
        if conc_max is not None:
            eb=collections.Counter()
            for q in range(min(30,len(ts))):
                if side[q]=="buy": eb[who[q]]+=usd[q]
            tot=sum(eb.values())
            if not tot or sum(v for _,v in eb.most_common(3))/tot>conc_max: continue
        seen=set(); devsold=False; trig=None
        for i in range(len(ts)):
            if who[i]==P["creator"] and side[i]=="sell": devsold=True
            if side[i]!="buy": continue
            w=who[i]
            if w in smart and w not in seen and ts[i]>=T:
                if (nodev and devsold) or px[i]*1e9>mc_hi: break
                trig=(i,w); break
            seen.add(w)
        if not trig: continue
        i,leader=trig; t_in=ts[i]+lat
        if T_end and t_in+tmax>T_end: continue
        j=bisect.bisect_left(ts,t_in)
        if j>=len(ts): continue
        k=P["k"]; pe=px[j]; tok=bt.buy(size,pe,k); left=tok; got=0.0
        x=(size-bt.fomo_fee(size))*0.99/bt.SOLUSD; vS=math.sqrt(pe/bt.SOLUSD*k); lift=((vS+x)/vS)**2
        lsell=next((ts[n] for n in range(i+1,len(ts)) if who[n]==leader and side[n]=="sell"),None)
        half=False; hi=pe; why="end"; pxx=px[-1]
        for n in range(j+1,len(ts)):
            if ts[n]-t_in<lat: continue
            p=px[n]; hi=max(hi,p)
            if not half and p<=pe*(1-stop): why="stop"; pxx=p; break
            if not half and lsell and ts[n]>=lsell+lat: got+=bt.sell(left*0.5,p*lift,k); left*=0.5; half=True; hi=p; continue
            if half and p<=hi*0.7: why="trail"; pxx=p; break
            if ts[n]-t_in>tmax: why="time"; pxx=p; break
        got+=bt.sell(left,pxx*lift,k)
        out.append(dict(m=m,pnl=got-size,why=why))
    return out
def rep(r,size=100):
    if not r: return "n=0"
    pn=sorted([x["pnl"] for x in r],reverse=True); top=max(1,len(pn)//50)
    return f"n={len(r):3d} roi={100*sum(pn)/size/len(pn):+6.1f}% win={100*sum(p>0 for p in pn)/len(pn):3.0f}% median={100*st.median(pn)/size:+6.1f}% ex_top2%={100*sum(pn[top:])/size/len(pn):+6.1f}%"
if __name__=="__main__":
    allts=sorted(t for P in PRE.values() for t in P["ts"])
    T_end=allts[-1]
    for q in (0.5,0.6,0.7,0.8):
        T=allts[int(len(allts)*q)]
        smart=skill_before(T)
        print(f"cutoff {dt.datetime.utcfromtimestamp(T):%m-%d %H:%M} UTC (q={q}): {len(smart)} proven wallets (past-only)")
        print("   v4 rule (bundle<=60%, dev not sold): ",rep(trade_after(T,smart,T_end=T_end)))
        print("   no bundle filter:                    ",rep(trade_after(T,smart,conc_max=None,T_end=T_end)))
        print("   no filters, all coins:              ",rep(trade_after(T,smart,conc_max=None,nodev=False,full_only=False,T_end=T_end)),flush=True)
