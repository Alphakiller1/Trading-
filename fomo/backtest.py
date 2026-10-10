import json, math, collections, statistics as st, itertools, sys
def F(x):
    try: return float(x) if x is not None else 0.0
    except Exception: return 0.0
coins=json.load(open("coins.json")); T={m:[t for t in v if t.get("priceUsd")] for m,v in json.load(open("trades.json")).items()}
SOLUSD=110.0; K_DEF=20.27*1.066e9
def fomo_fee(usd):
    if usd<5: return 0.10
    if usd<47.5: return usd*0.02
    if usd<190: return 0.95
    return usd*0.005
def kcoin(m):
    c=coins.get(m,{})
    try: return (c["virtual_sol_reserves"]/1e9)*(c["virtual_token_reserves"]/1e6) if not c.get("complete") else K_DEF
    except Exception: return K_DEF
def buy(usd,price_usd,k):
    # returns tokens received; pump fee 1% + fomo fee taken from usd
    x=(usd-fomo_fee(usd))*0.99/SOLUSD; p=price_usd/SOLUSD; vS=math.sqrt(p*k); vT=k/vS
    return vT-k/(vS+x)
def sell(tokens,price_usd,k):
    p=price_usd/SOLUSD; vS=math.sqrt(p*k); vT=k/vS
    sol=vS-k/(vT+tokens); usd=sol*SOLUSD*0.99
    return usd-fomo_fee(usd)
tapes={}
for m,tr in T.items():
    tr=sorted(tr,key=lambda t:t["slotIndexId"])
    if len(tr)<40: continue
    tapes[m]=[(int(t["slotIndexId"][:10]) if False else None, t["timestamp"], F(t["priceUsd"]), F(t["amountUsd"])) for t in tr]
import datetime as dt
def sec(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
for m in tapes: tapes[m]=[(sec(a[1]),a[2],a[3]) for a in tapes[m]]
def bars(tape,bs):
    out=[];cur=None
    for t,p,u in tape:
        b=int(t//bs)
        if cur is None or b!=cur[0]:
            if cur: out.append(cur)
            cur=[b,p,p,p,p,0.0,0.0]  # bucket o h l c usd vwapnum
        cur[2]=max(cur[2],p);cur[3]=min(cur[3],p);cur[4]=p;cur[5]+=u;cur[6]+=u*p
    if cur: out.append(cur)
    return out
def run(P,size_mode="fixed",verbose=False):
    res=[]
    for m,tape in tapes.items():
        k=kcoin(m); B=bars(tape,P["bs"])
        if len(B)<P["vw"]+3: continue
        ema=None; e=[]
        for b in B:
            ema=b[4] if ema is None else ema+(2/(9+1))*(b[4]-ema); e.append(ema)
        i=P["vw"]+1; busy_until=-1
        while i<len(B)-1:
            if B[i][0]*P["bs"]<busy_until: i+=1; continue
            w=B[i-P["vw"]:i+1]; vw=sum(x[6] for x in w)/max(sum(x[5] for x in w),1e-9)
            wp=B[i-P["vw"]:i]; vwp=sum(x[6] for x in wp)/max(sum(x[5] for x in wp),1e-9)
            mc=B[i][4]*1e9
            avgv=sum(x[5] for x in B[i-5:i])/5
            cross=e[i-1]<=vwp and e[i]>vw
            if cross and B[i][5]>=P["vm"]*max(avgv,1) and P["mc_lo"]<=mc<=P["mc_hi"]:
                rets=[math.log(B[j][4]/B[j-1][4]) for j in range(i-19,i+1) if B[j-1][4]>0]
                vol=st.pstdev(rets) if len(rets)>3 else 0.05
                if size_mode=="fixed": usd=P["usd"]
                else: usd=max(25,min(250, P["vt"]/max(vol,1e-6)))  # inverse-vol sizing
                tsig=(B[i][0]+1)*P["bs"]+P.get("lat",3)
                # entry at first trade after signal bar end + latency
                j=next((n for n,(t,p,u) in enumerate(tape) if t>=tsig),None)
                if j is None: break
                pe=tape[j][1]; tok=buy(usd,pe,k); hi=pe; px=pe; why="end"
                for t,p,u in tape[j+1:]:
                    hi=max(hi,p); px=p
                    if p<=pe*(1-P["stop"]): why="stop";break
                    if hi>=pe*(1+P["act"]) and p<=hi*(1-P["trail"]): why="trail";break
                    if t-tape[j][0]>P["tmax"]: why="time";break
                else: t=tape[-1][0]
                out=sell(tok,px,k)
                res.append(dict(m=m,usd=usd,pnl=out-usd,ret=px/pe-1,why=why,mc=mc,vol=vol))
                busy_until=t; 
            i+=1
    return res
def summ(r):
    if not r: return "no trades"
    pn=[x["pnl"] for x in r]; w=[x for x in pn if x>0]
    return f"n={len(r)} win%={100*len(w)/len(r):.1f} net=${sum(pn):.0f} per$={sum(pn)/sum(x['usd'] for x in r)*100:.1f}% avgret={100*st.mean(x['ret'] for x in r):.1f}% medret={100*st.median(x['ret'] for x in r):.1f}% exits={dict(collections.Counter(x['why'] for x in r))}"
if __name__=="__main__":
    base=dict(bs=5,vw=50,vm=1.5,mc_lo=0,mc_hi=80000,usd=100,stop=0.01,act=0.01,trail=0.02,tmax=3600,lat=3,vt=5)
    print("coins with tapes",len(tapes))
    print("TWS rules as-is (5s bars, 1% stop, 2% trail) $100:",summ(run(base)))
    for usd in (25,100,250):
        print(f" size ${usd}:",summ(run({**base,"usd":usd})))
