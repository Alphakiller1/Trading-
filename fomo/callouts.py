"""Collect callout histories (pump.fun/fomo-style public calls) and test whether a caller's PAST record predicts the NEXT call."""
import requests, json, time, collections, statistics as st, sys, os
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36","Origin":"https://pump.fun","Referer":"https://pump.fun/"}
B="https://frontend-api-v3.pump.fun"; S=requests.Session(); S.headers.update(H)
def get(u,p=None):
    for i in range(2):
        try:
            r=S.get(u,params=p,timeout=8)
            if r.ok: return r.json()
            if r.status_code==429: time.sleep(5*(i+1)); continue
            return None
        except Exception: time.sleep(2)
if "--collect" in sys.argv:
    callers=set()
    for _ in range(3):
        for c in (get(f"{B}/home-feed",dict(pageSize=150,chain="all",platform="WEB")) or {}).get("coins",[]):
            pos=c.get("position") or {}
            if pos.get("walletAddress"): callers.add(pos["walletAddress"])
        time.sleep(2)
    for per in ("daily","weekly","monthly"):
        for e in (get(f"{B}/pnl-leaderboard",dict(period=per,sort="combined",limit=100)) or {}).get("entries",[]): callers.add(e["walletAddress"])
    print("callers to fetch:",len(callers),flush=True)
    data={}
    for i,w in enumerate(sorted(callers)):
        d=get(f"{B}/callout/list/{w}",dict(limit=100,sortBy="TIMESTAMP",sortOrder="DESC"))
        if d and d.get("callouts"): data[w]=d["callouts"]
        time.sleep(0.35)
        if i%10==0:
            print(i,len(data),flush=True); json.dump(data,open("callouts.json","w"))
    json.dump(data,open("callouts.json","w")); print("callers with callouts:",len(data),"total callouts:",sum(map(len,data.values())))
    sys.exit()
data=json.load(open("callouts.json"))
now=time.time()*1000
rows=[]
for w,cs in data.items():
    cs=sorted([c for c in cs if c.get("marketCap") and c.get("maxMultiplier") and c.get("multiple") is not None and c.get("chain") in (None,"solana") and not c.get("perp")],key=lambda c:c["createdAt"])
    for k,c in enumerate(cs):
        if now-c["createdAt"]<24*3600e3: continue                  # outcome needs >=24h to develop
        prior=[p for p in cs[:k] if c["createdAt"]-p["createdAt"]>=24*3600e3]   # only calls whose 24h+ outcome was knowable then
        rows.append(dict(w=w,t=c["createdAt"],mc=c["marketCap"],maxm=c["maxMultiplier"],cur=c["multiple"],
                         n_prior=len(prior),prior_hit2=(sum(p["maxMultiplier"]>=2 for p in prior)/len(prior)) if prior else None,
                         prior_med=(st.median(p["maxMultiplier"] for p in prior)) if prior else None))
rows.sort(key=lambda r:r["t"])
print("callouts with >=24h outcome:",len(rows),"| callers:",len({r['w'] for r in rows}))
def proxy(r,tp=2.0,cost=0.06,haircut=0.10):
    """Buy ~10% above call price (latency), sell at tp x if the max reached it, else exit at current multiple. 6% costs."""
    entry=1+haircut
    exit_=tp*1.0 if r["maxm"]>=tp*entry else r["cur"]
    return exit_/entry-1-cost
def rep(name,rs,tp=2.0):
    if len(rs)<10: print(f" {name:44s} n={len(rs)}"); return
    p=[proxy(r,tp) for r in rs]; h=len(rs)//2
    print(f" {name:44s} n={len(rs):4d} hit {tp}x {100*sum(r['maxm']>=tp*1.1 for r in rs)/len(rs):5.1f}%  avg {100*st.mean(p):+6.1f}%  median {100*st.median(p):+6.1f}% | earlier {100*st.mean(p[:h]):+6.1f}% later {100*st.mean(p[h:]):+6.1f}%")
small=[r for r in rows if r["mc"]<200000]
print("\n== calls under $200k mcap, proxy trade: enter +10% above call, take profit 2x else hold, 6% costs ==")
rep("all calls < $200k",small)
rep("calls < $50k",[r for r in small if r["mc"]<50000])
rep("calls $50k-200k",[r for r in small if r["mc"]>=50000])
rep("caller with 0 prior known calls",[r for r in small if r["n_prior"]==0])
rep("caller >=5 prior, prior 2x-rate >= 30%",[r for r in small if r["n_prior"]>=5 and r["prior_hit2"]>=0.3])
rep("caller >=5 prior, prior 2x-rate >= 50%",[r for r in small if r["n_prior"]>=5 and r["prior_hit2"]>=0.5])
rep("caller >=5 prior, prior 2x-rate < 20%",[r for r in small if r["n_prior"]>=5 and r["prior_hit2"]<0.2])
rep("caller >=10 prior, prior median >= 1.5x",[r for r in small if r["n_prior"]>=10 and r["prior_med"]>=1.5])
for tp in (1.5,3.0):
    rep(f"all < $200k, take profit {tp}x",small,tp)
    rep(f"good callers (>=5, 2x-rate>=30%), tp {tp}x",[r for r in small if r["n_prior"]>=5 and r["prior_hit2"]>=0.3],tp)
