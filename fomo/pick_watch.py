"""Live pick for a $23 trade: copy signal + v2 tier score. mc <= $100k."""
import json, collections, statistics as st, time, requests, datetime as dt, concurrent.futures as cf, bisect
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36","Origin":"https://pump.fun","Referer":"https://pump.fun/"}
B="https://frontend-api-v3.pump.fun"; CH="solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
S=requests.Session(); S.headers.update(H)
pos=json.load(open("positions.json"))
BL=set(l.strip() for l in open("blacklist.txt"))
acc=collections.defaultdict(lambda:[0,0.0,0.0,[]])
for p in pos:
    if p["dev"] or p["max_buy"]>1000: continue
    a=acc[p["w"]]; a[0]+=1; a[1]+=p["pnl"]; a[2]+=p["buy_usd"]; a[3].append(p["hold"])
smart={w:a for w,a in acc.items() if w not in BL and a[0]>=3 and a[2]>0 and a[1]/a[2]>0 and st.median(a[3])>=20}
def sec(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
def get(u,p):
    for i in range(3):
        try:
            r=S.get(u,params=p,timeout=10)
            if r.ok: return r.json()
        except Exception: pass
        time.sleep(1.5*(i+1))
coins={}
for sort in ("last_trade_timestamp",):
    for off in range(0,400,50):
        for c in get(f"{B}/coins",dict(offset=off,limit=50,sort=sort,order="DESC",includeNsfw="false")) or []: coins[c["mint"]]=c
now=time.time()
def check(c):
    m=c["mint"]; mc=c.get("usd_market_cap") or 0
    if not (4000<=mc<=100000): return None
    pre=get(f"https://swap-api.pump.fun/v2/coins/{m}/trades",dict(limit=100,program="pump",chainId=CH))
    if not pre or not any(t["type"]=="buy" and t["userAddress"] in smart and now-sec(t["timestamp"])<=330 for t in pre["trades"]): return None
    tr=[];cur=None;full=False
    for _ in range(10):
        p=dict(limit=100,program="pump",chainId=CH)
        if cur: p["cursor"]=cur
        d=get(f"https://swap-api.pump.fun/v2/coins/{m}/trades",p)
        if not d: break
        tr+=d["trades"]
        if not d["pagination"]["hasMore"]: full=True; break
        cur=d["pagination"]["nextCursor"]
    if not full: return None
    tr=sorted([t for t in tr if t.get("priceUsd")],key=lambda t:t["slotIndexId"])
    creator=c.get("creator")
    devsold=any(t["userAddress"]==creator and t["type"]=="sell" for t in tr)
    eb=collections.Counter()
    for t in tr[:30]:
        if t["type"]=="buy": eb[t["userAddress"]]+=float(t["amountUsd"] or 0)
    tot=sum(eb.values()); conc=sum(v for _,v in eb.most_common(3))/tot if tot else 1
    seen=set(); first=None
    for t in tr:
        if t["type"]=="buy" and t["userAddress"] in smart and t["userAddress"] not in seen: first=t; break
        if t["type"]=="buy": seen.add(t["userAddress"])
    if not first: return None
    age_sig=now-sec(first["timestamp"])
    ts=[sec(t["timestamp"]) for t in tr]; px=[float(t["priceUsd"]) for t in tr]
    lo=bisect.bisect_left(ts,now-300); w=px[lo:] or px[-1:]
    vol=max(w)/min(w)-1
    last5=[t for t in tr if now-sec(t["timestamp"])<=300]
    net=sum(float(t["amountUsd"] or 0)*(1 if t["type"]=="buy" else -1) for t in last5)
    buyers=len({t["userAddress"] for t in last5 if t["type"]=="buy"})
    lead=smart[first["userAddress"]]
    tw=(c.get("twitter") or "").lower(); social=bool(c.get("website") or c.get("telegram") or (tw and "/status/" not in tw))
    score=(2 if conc<=0.6 else 1 if conc<=0.8 else 0)+(0 if devsold else 1)+(1 if lead[0]>=5 else 0)+(1 if social else 0)
    trig=float(first["priceUsd"])*1e9; cur_mc=px[-1]*1e9
    leader_sold=any(t["userAddress"]==first["userAddress"] and t["type"]=="sell" for t in tr)
    return dict(sym=c.get("symbol"),name=c.get("name"),mint=m,mc=round(cur_mc),trig=round(trig),chase=round((cur_mc/trig-1)*100),
                sig_age_s=round(age_sig),score=score,conc=round(conc,2),devsold=devsold,vol5=round(vol*100),net5=round(net),buyers5=buyers,
                leader=first["userAddress"],lead_n=lead[0],lead_roi=round(lead[1]/lead[2]*100),lead_buy=round(float(first["amountUsd"] or 0)),
                leader_sold=leader_sold,social=social,twitter=c.get("twitter"),website=c.get("website"),telegram=c.get("telegram"),
                age_h=round((now-c["created_timestamp"]/1000)/3600,2),ath=round(c.get("ath_market_cap") or 0))
with cf.ThreadPoolExecutor(4) as ex: res=[r for r in ex.map(check,coins.values()) if r]
res.sort(key=lambda r:(-(r["score"]),r["devsold"],r["leader_sold"],-r["net5"]))
json.dump(res,open("picks.json","w"),indent=1)
for r in res:
    base=not r["devsold"] and not r["leader_sold"] and r["vol5"]>=12 and -30<=r["chase"]<=30 and r["sig_age_s"]<=300 and r["mc"]<=100000
    if base and r["score"]>=3:
        tier=("T3 $130-250" if r["score"]==5 and r["vol5"]<32 else "T2 $60-125" if r["score"]==5 else "T1 $20-55") if r["score"]>=4 else "LOWER-QUALITY (score 3)"
        print(time.strftime("%H:%M:%S"),"QUALIFIED",tier,json.dumps(r),flush=True)
