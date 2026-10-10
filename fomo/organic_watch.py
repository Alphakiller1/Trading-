import json, collections, time, requests, datetime as dt, concurrent.futures as cf, bisect
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36","Origin":"https://pump.fun","Referer":"https://pump.fun/"}
B="https://frontend-api-v3.pump.fun"; CH="solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
S=requests.Session(); S.headers.update(H)
def sec(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
def get(u,p):
    for i in range(3):
        try:
            r=S.get(u,params=p,timeout=10)
            if r.ok: return r.json()
        except Exception: pass
        time.sleep(1.5*(i+1))
coins={}
for off in range(0,400,50):
    for c in get(f"{B}/coins",dict(offset=off,limit=50,sort="last_trade_timestamp",order="DESC",includeNsfw="false")) or []: coins[c["mint"]]=c
now=time.time()
cand=[c for c in coins.values() if 10000<=(c.get("usd_market_cap") or 0)<=100000 and (now-c["created_timestamp"]/1000)>=1800]

def stage1(c):
    d=get(f"https://swap-api.pump.fun/v2/coins/{c['mint']}/trades",dict(limit=100,program="pump",chainId=CH))
    if not d: return None
    tr=sorted([t for t in d["trades"] if t.get("priceUsd")],key=lambda t:t["slotIndexId"])
    l5=[t for t in tr if now-sec(t["timestamp"])<=300]
    if len(l5)<10: return None
    px=[float(t["priceUsd"]) for t in l5]; vol=max(px)/min(px)-1
    net=sum(float(t["amountUsd"] or 0)*(1 if t["type"]=="buy" else -1) for t in l5)
    buyers=len({t["userAddress"] for t in l5 if t["type"]=="buy"})
    p15=[float(t["priceUsd"]) for t in tr if now-sec(t["timestamp"])<=900]
    trend=(px[-1]/p15[0]-1) if p15 else 0
    return dict(c=c,vol=vol,net=net,buyers=buyers,mc=px[-1]*1e9,trend15=trend)
with cf.ThreadPoolExecutor(4) as ex: s1=[r for r in ex.map(stage1,cand) if r]
s1=[r for r in s1 if 0.12<=r["vol"]<=0.60 and r["net"]>0 and r["buyers"]>=20]

def stage2(r):
    c=r["c"]; tr=[];cur=None;full=False
    for _ in range(10):
        p=dict(limit=100,program="pump",chainId=CH)
        if cur: p["cursor"]=cur
        d=get(f"https://swap-api.pump.fun/v2/coins/{c['mint']}/trades",p)
        if not d: break
        tr+=d["trades"]
        if not d["pagination"]["hasMore"]: full=True; break
        cur=d["pagination"]["nextCursor"]
    tr=sorted([t for t in tr if t.get("priceUsd")],key=lambda t:t["slotIndexId"])
    devsold=any(t["userAddress"]==c.get("creator") and t["type"]=="sell" for t in tr)
    conc=None
    if full:
        eb=collections.Counter()
        for t in tr[:30]:
            if t["type"]=="buy": eb[t["userAddress"]]+=float(t["amountUsd"] or 0)
        tot=sum(eb.values()); conc=sum(v for _,v in eb.most_common(3))/tot if tot else 1
    tw=(c.get("twitter") or "").lower()
    return dict(sym=c.get("symbol"),name=c.get("name"),mint=c["mint"],mc=round(r["mc"]),age_h=round((now-c["created_timestamp"]/1000)/3600,1),
                vol5=round(r["vol"]*100),net5=round(r["net"]),buyers5=r["buyers"],trend15=round(r["trend15"]*100),devsold=devsold,
                conc=None if conc is None else round(conc,2),history_complete=full,ath=round(c.get("ath_market_cap") or 0),
                social="web/tg" if (c.get("website") or c.get("telegram")) else "x_profile" if tw and "/status/" not in tw else "tweet" if tw else "none",
                twitter=c.get("twitter"),website=c.get("website"))
with cf.ThreadPoolExecutor(4) as ex: s2=list(ex.map(stage2,s1))
s2=[x for x in s2 if not x["devsold"]]
s2.sort(key=lambda x:(-(x["conc"] is not None and x["conc"]<=0.6), -x["net5"]))
import os
seen=set(open("organic_seen.txt").read().split()) if os.path.exists("organic_seen.txt") else set()
for x in s2[:10]:
    if x["mint"] in seen: continue
    open("organic_seen.txt","a").write(x["mint"]+"\n")
    risk=[]
    if x["social"] in ("tweet","none"): risk.append("weak socials")
    if x["ath"] and x["mc"]<0.5*x["ath"]: risk.append(f"down {100-100*x['mc']//x['ath']}% from ATH")
    if x["conc"] is not None and x["conc"]>0.6: risk.append("bundled launch")
    if x["conc"] is None: risk.append("bundle check n/a")
    print(time.strftime("%H:%M:%S"),f"CANDIDATE {x['sym']} {x['mint']} mc ${x['mc']:,} | age {x['age_h']}h | vol5 {x['vol5']}% | net5 ${x['net5']:+,} from {x['buyers5']} buyers | 15m trend {x['trend15']:+d}% | ATH ${x['ath']:,} | socials {x['social']} | entry <= ${int(x['mc']*1.07):,}, target ${int(x['mc']*1.7):,}, stop ${int(x['mc']*0.7):,} | risks: {', '.join(risk) or 'none flagged'}",flush=True)
