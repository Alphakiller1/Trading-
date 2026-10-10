"""Size tiers: $20-55 / $60-125 / $130-250 by predictability, volatility and market cap.
Score is pre-specified (not fitted). Each trade is re-simulated at its tier's size with full costs."""
import collections, statistics as st, math, bisect, re
import copy4 as C
full={m for m,P in C.PRE.items() if len(P["ts"])<1000}
BASE=dict(mc_hi=200000,half_mirror=True,rest_trail=0.3)       # v4 exits, no entry filters -> filters become score inputs
runs={sz:{(x["m"]):x for x in C.run(size=sz,**BASE) if x["m"] in full} for sz in (40,100,200)}
pos_n=collections.Counter(p["w"] for p in C.pos)
def feats(x):
    P=C.PRE[x["m"]]; i=x["i"]; ts,px,usd,side,who=P["ts"],P["px"],P["usd"],P["side"],P["who"]
    eb=collections.Counter()
    for q in range(min(30,len(ts))):
        if side[q]=="buy": eb[who[q]]+=usd[q]
    tot=sum(eb.values()); conc=sum(v for _,v in eb.most_common(3))/tot if tot else 1
    devsold=any(who[q]==P["creator"] and side[q]=="sell" for q in range(i))
    lo=bisect.bisect_left(ts,ts[i]-300); w=px[lo:i+1]
    vol=max(w)/min(w)-1 if w and min(w)>0 else 0
    c=C.coins.get(x["m"],{}); tw=(c.get("twitter") or "").lower()
    social=bool(c.get("website") or c.get("telegram") or (tw and "/status/" not in tw))
    score=(2 if conc<=0.6 else 1 if conc<=0.8 else 0)+(0 if devsold else 1)+(1 if pos_n[x["leader"]]>=5 else 0)+(1 if social else 0)
    return dict(conc=conc,devsold=devsold,vol=vol,mc=px[i]*1e9,score=score,social=social)
F={m:feats(x) for m,x in runs[100].items()}
vol_med=st.median(f["vol"] for f in F.values())
def roi(ms,sz):
    rr=[runs[sz][m] for m in ms if m in runs[sz]]
    if not rr: return "n=0"
    pn=sorted([x["pnl"] for x in rr],reverse=True); top=max(1,len(pn)//50)
    A=[x for x in rr if x["h"]==0]; Bh=[x for x in rr if x["h"]==1]
    f=lambda r: f"{100*sum(x['pnl'] for x in r)/sz/len(r):+6.1f}%({len(r)})" if r else "  -  "
    return f"n={len(rr):3d} roi={100*sum(pn)/sz/len(pn):+6.1f}% win={100*sum(p>0 for p in pn)/len(pn):3.0f}% ex_top2%={100*sum(pn[top:])/sz/len(pn):+6.1f}% A {f(A)} B {f(Bh)}"
print(f"trades: {len(F)}  median 5-min range (volatility) before entry: {vol_med*100:.0f}%")
print("\n== by predictability score (0-5) at $100 ==")
for s in range(6):
    ms=[m for m,f in F.items() if f["score"]==s]
    if ms: print(f" score {s}: {roi(ms,100)}")
print("\n== by volatility (5-min range before entry) at $100 ==")
qs=sorted(f["vol"] for f in F.values()); cuts=[qs[len(qs)//3],qs[2*len(qs)//3]]
for name,cond in [(f"low  (<{cuts[0]*100:.0f}%)",lambda v:v<cuts[0]),(f"mid",lambda v:cuts[0]<=v<cuts[1]),(f"high (>={cuts[1]*100:.0f}%)",lambda v:v>=cuts[1])]:
    print(f" {name:16s} {roi([m for m,f in F.items() if cond(f['vol'])],100)}")
print("\n== by market cap at entry, $100 ==")
for lo,hi in ((0,15e3),(15e3,40e3),(40e3,80e3),(80e3,2e5)):
    print(f" ${lo/1e3:.0f}k-{hi/1e3:.0f}k".ljust(17),roi([m for m,f in F.items() if lo<=f['mc']<hi],100))
# ---- tier assignment (pre-specified) ----
def tier(f):
    if f["devsold"] or f["score"]<=1: return "skip"
    if f["score"]>=4 and f["vol"]<vol_med: return "T3 $130-250"
    if f["score"]>=3: return "T2 $60-125"
    return "T1 $20-55"
size={"T1 $20-55":40,"T2 $60-125":100,"T3 $130-250":200,"skip":100}
print("\n== TIERS (each trade simulated at its tier size) ==")
for t in ("T3 $130-250","T2 $60-125","T1 $20-55","skip"):
    ms=[m for m,f in F.items() if tier(f)==t]
    print(f" {t:12s} {roi(ms,size[t])}")
tot=sum(runs[size[tier(f)]][m]["pnl"] for m,f in F.items() if tier(f)!="skip" and m in runs[size[tier(f)]])
inv=sum(size[tier(f)] for f in F.values() if tier(f)!="skip")
print(f"\n tiered portfolio: ${tot:+.2f} on ${inv} deployed ({100*tot/inv:+.1f}%)  vs flat $100 on all: {roi(list(F),100)}")

# ---- v2 tiers, revised after the volatility finding (IN-SAMPLE: needs paper validation) ----
V_LO,V_HI=0.12,0.32
def tier2(f):
    if f["devsold"] or f["vol"]<V_LO or f["score"]<=3: return "skip"
    if f["score"]==5 and f["vol"]<V_HI: return "T3 $130-250"
    if f["score"]==5: return "T2 $60-125"
    return "T1 $20-55"                       # score 4
print("\n== TIERS v2: score 5 + mid vol -> T3; score 5 + high vol -> T2; score 4 -> T1; dev sold / vol<12% / score<=3 -> skip ==")
for t in ("T3 $130-250","T2 $60-125","T1 $20-55","skip"):
    ms=[m for m,f in F.items() if tier2(f)==t]
    print(f" {t:12s} {roi(ms,size[t])}")
tot=sum(runs[size[tier2(f)]][m]["pnl"] for m,f in F.items() if tier2(f)!="skip" and m in runs[size[tier2(f)]])
inv=sum(size[tier2(f)] for f in F.values() if tier2(f)!="skip")
print(f" tiered v2 portfolio: ${tot:+.2f} on ${inv} deployed ({100*tot/inv:+.1f}%)")
