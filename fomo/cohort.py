"""Unbiased cohort: every launch logged live, first 30 min of trades. Base rates + which launch-time features predict outcomes."""
import json, collections, datetime as dt, statistics as st
def sec(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
rows=[]
for l in open("live/coins.jsonl"):
    d=json.loads(l); c=d["coin"]; tr=sorted([t for t in d["trades"] if t.get("priceUsd")],key=lambda t:t["slotIndexId"])
    if not tr: rows.append(dict(peak=0,n=0)); continue
    t0=c["created_timestamp"]/1000
    mc=[float(t["priceUsd"])*1e9 for t in tr]; ts=[sec(t["timestamp"]) for t in tr]
    eb=collections.Counter()
    for t in tr[:30]:
        if t["type"]=="buy": eb[t["userAddress"]]+=float(t["amountUsd"] or 0)
    tot=sum(eb.values()); conc=sum(v for _,v in eb.most_common(3))/tot if tot else 1
    first_dev_sell=next((ts[i]-t0 for i,t in enumerate(tr) if t["userAddress"]==c["creator"] and t["type"]=="sell"),None)
    early=[t for t in tr if sec(t["timestamp"])-t0<=60]
    tw=(c.get("twitter") or "").lower()
    rows.append(dict(peak=max(mc),final=mc[-1],n=len(tr),conc=conc,dev_sell_min=None if first_dev_sell is None else first_dev_sell/60,
        social="web/tg" if (c.get("website") or c.get("telegram")) else "x_profile" if tw and "/status/" not in tw else "tweet" if tw else "none",
        buyers_1m=len({t["userAddress"] for t in early if t["type"]=="buy"}),vol_1m=sum(float(t["amountUsd"] or 0) for t in early),
        hour=dt.datetime.utcfromtimestamp(t0).hour, mc_1m=mc[len(early)-1] if early else mc[0]))
N=len(rows); print(f"launches logged: {N}")
for th in (5e3,10e3,20e3,30e3,69e3):
    print(f"  peak >= ${th/1e3:.0f}k within 30 min: {100*sum(r['peak']>=th for r in rows)/N:5.1f}%")
def rate(name,rs,th=30e3):
    if len(rs)<10: return
    print(f"  {name:32s} n={len(rs):4d}  reach $30k {100*sum(r['peak']>=th for r in rs)/len(rs):5.1f}%  reach $10k {100*sum(r['peak']>=1e4 for r in rs)/len(rs):5.1f}%  final/peak med {st.median([r['final']/r['peak'] for r in rs if r['peak']]):.2f}")
R=[r for r in rows if r["n"]]
print("by social type:"); [rate(k,[r for r in R if r["social"]==k]) for k in ("web/tg","x_profile","tweet","none")]
print("by early concentration (top-3 share of first-30-trade buys):")
for lo,hi in ((0,.4),(.4,.6),(.6,.8),(.8,1.01)): rate(f"{lo:.0%}-{hi:.0%}",[r for r in R if lo<=r["conc"]<hi])
print("by dev selling:")
rate("dev sold within 2 min",[r for r in R if r["dev_sell_min"] is not None and r["dev_sell_min"]<2])
rate("dev sold 2-30 min",[r for r in R if r["dev_sell_min"] is not None and r["dev_sell_min"]>=2])
rate("dev never sold (30 min)",[r for r in R if r["dev_sell_min"] is None])
print("by buyers in first minute:")
for lo,hi in ((0,5),(5,15),(15,40),(40,1e9)): rate(f"{lo}-{hi} buyers",[r for r in R if lo<=r["buyers_1m"]<hi])
print("combined filter (conc<=60%, dev not sold in 2 min, socials web/tg or x_profile):")
rate("passes",[r for r in R if r["conc"]<=.6 and not (r["dev_sell_min"] is not None and r["dev_sell_min"]<2) and r["social"] in ("web/tg","x_profile")])
rate("fails",[r for r in R if not (r["conc"]<=.6 and not (r["dev_sell_min"] is not None and r["dev_sell_min"]<2) and r["social"] in ("web/tg","x_profile"))])
