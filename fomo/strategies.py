"""Manual-executable strategy candidates for fomo, simulated on pump.fun trade tapes.
Costs: fomo fee tiers + 1% pump fee per side + constant-product slippage. Latency = human reaction."""
import json, math, statistics as st, hashlib, collections, sys
import backtest as bt   # tapes, kcoin, buy, sell, fomo_fee
coins=bt.coins; TAPES=bt.tapes
def split(m): return int(hashlib.md5(m.encode()).hexdigest(),16)%2
def first_idx(tape,t0):
    lo,hi=0,len(tape)
    while lo<hi:
        mid=(lo+hi)//2
        if tape[mid][0]<t0: lo=mid+1
        else: hi=mid
    return lo if lo<len(tape) else None
def simulate(m,tape,tsig,usd,X,k):
    """enter at first trade >= tsig+lat; exits: stop from fill, scale-out at tp1, trailing on rest, time stop"""
    j=first_idx(tape,tsig+X["lat"])
    if j is None: return None
    pe=tape[j][1]; tok=bt.buy(usd,pe,k); left=tok; got=0.0; hi=pe; why="end"; t_in=tape[j][0]
    # our own buy lifts the curve; that lift persists while we hold, so sells start from tape price * own-impact
    x=(usd-bt.fomo_fee(usd))*0.99/bt.SOLUSD; vS=math.sqrt(pe/bt.SOLUSD*k); lift=((vS+x)/vS)**2
    tp_done=False; px=pe
    for t,p,u in tape[j+1:]:
        if t-t_in<X["lat"]: continue   # human can't react before latency
        hi=max(hi,p); px=p
        if not tp_done and p>=pe*(1+X["tp1"]):
            part=left*X["tp1_frac"]; got+=bt.sell(part,p*lift,k); left-=part; tp_done=True
        if p<=pe*(1-X["stop"]) and not tp_done: why="stop"; break
        if tp_done and p<=max(pe*1.0,hi*(1-X["trail"])): why="trail"; break
        if t-t_in>X["tmax"]: why="time"; break
    got+=bt.sell(left,px*lift,k) if left>0 else 0
    return dict(m=m,usd=usd,pnl=got-usd,why=why,ret=px/pe-1)
def bars(tape,bs):
    return bt.bars(tape,bs)
# ---------- entry rules: yield signal times ----------
def sig_launch(m,tape,P):
    c=coins.get(m,{}); t0=c.get("created_timestamp",0)/1000
    if not t0 or tape[0][0]-t0>20: return []      # need tape from launch
    # wait until coin is P["age"] seconds old and mcap within band and has >=N buyers
    for t,p,u in tape:
        if t-t0>=P["age"]:
            mc=p*1e9
            n=len({1 for x in tape if x[0]<=t})
            if P["lo"]<=mc<=P["hi"]: return [t]
            return []
    return []
def sig_cross(m,tape,P):
    """TWS: EMA9 crosses rolling VWAP with volume burst, on P['bs'] bars, in mcap band, coin age >= P['minage']"""
    c=coins.get(m,{}); t0=c.get("created_timestamp",0)/1000
    B=bars(tape,P["bs"]); out=[]; ema=None; e=[]
    for b in B:
        ema=b[4] if ema is None else ema+0.2*(b[4]-ema); e.append(ema)
    vw=P["vw"]
    for i in range(vw+1,len(B)):
        w=B[i-vw:i]; v=sum(x[6] for x in w)/max(sum(x[5] for x in w),1e-9)
        mc=B[i][4]*1e9; tb=(B[i][0]+1)*P["bs"]
        if not (P["lo"]<=mc<=P["hi"]) or tb-t0<P["minage"]: continue
        avgv=sum(x[5] for x in B[i-5:i])/5
        if e[i-1]<=v and e[i]>v and B[i][5]>=P["vm"]*max(avgv,1): out.append(tb)
    return out
def sig_gradzone(m,tape,P):
    """mcap first crosses P['cross'] from below with net buy USD over last 60s >= P['flow']"""
    out=[]; below=False
    for i,(t,p,u) in enumerate(tape):
        mc=p*1e9
        if mc<P["cross"]*0.9: below=True
        if below and mc>=P["cross"]:
            # net flow approx: sum of usd where price rose vs fell
            w=[x for x in tape[max(0,i-300):i+1] if x[0]>=t-60]
            up=sum(x[2] for a,x in zip(w,w[1:]) if x[1]>=a[1]); dn=sum(x[2] for a,x in zip(w,w[1:]) if x[1]<a[1])
            if up-dn>=P["flow"]: out.append(t)
            below=False
    return out
SIGS=dict(launch=sig_launch,cross=sig_cross,gradzone=sig_gradzone)
def evaluate(kind,P,X,sizes=(25,100,250),half=None,cooldown=True):
    rows=[]
    for m,tape in TAPES.items():
        if half is not None and split(m)!=half: continue
        k=bt.kcoin(m); busy=-1
        for ts in SIGS[kind](m,tape,P):
            if ts<busy: continue
            r={}
            for s in sizes:
                x=simulate(m,tape,ts,s,X,k)
                if x: r[s]=x
            if r: rows.append(r)
            if cooldown: busy=float("inf")      # one trade per coin (no re-entry)
    return rows
def report(rows,s):
    r=[x[s] for x in rows if s in x]
    if len(r)<10: return f"n={len(r)} (too few)"
    pn=sorted([x["pnl"] for x in r],reverse=True); inv=sum(x["usd"] for x in r)
    top=max(1,len(pn)//100)
    return (f"n={len(r)} win%={100*sum(p>0 for p in pn)/len(pn):.0f} roi={100*sum(pn)/inv:+.1f}% "
            f"med={100*st.median(pn)/s:+.1f}% roi_ex_top1%={100*sum(pn[top:])/inv:+.1f}% exits={dict(collections.Counter(x['why'] for x in r))}")
