"""Live scan: coins where a proven small wallet just made its FIRST buy, with safety filters."""
import json, collections, statistics as st, time, requests, datetime as dt, concurrent.futures as cf
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36","Origin":"https://pump.fun","Referer":"https://pump.fun/"}
B="https://frontend-api-v3.pump.fun"; CH="solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
S=requests.Session(); S.headers.update(H)
pos=json.load(open("positions.json"))
acc=collections.defaultdict(lambda:[0,0.0,0.0,0,[]])
for p in pos:
    if p["dev"] or p["max_buy"]>1000: continue
    a=acc[p["w"]]; a[0]+=1; a[1]+=p["pnl"]; a[2]+=p["buy_usd"]; a[3]+=p["pnl"]>0; a[4].append(p["hold"])
BL=set(l.strip() for l in open('blacklist.txt')) if __import__('os').path.exists('blacklist.txt') else set()
smart={w:(a[1]/a[2],a[0],a[3]/a[0]) for w,a in acc.items() if w not in BL and a[0]>=3 and a[2]>0 and a[1]/a[2]>0 and st.median(a[4])>=20}

def sec(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
def get(u,p):
    try:
        r=S.get(u,params=p,timeout=15); return r.json() if r.ok else None
    except Exception: return None
coins={}
for off in range(0,300,50):
    for c in get(f"{B}/coins",dict(offset=off,limit=50,sort="last_trade_timestamp",order="DESC",includeNsfw="false")) or []:
        coins[c["mint"]]=c
now=time.time()
def check(c):
    m=c["mint"]; mc=c.get("usd_market_cap") or 0
    if not (5000<=mc<=200000): return None
    tr=[]; cur=None
    full=False
    for _ in range(30):
        p=dict(limit=100,program="pump",chainId=CH)
        if cur: p["cursor"]=cur
        d=get(f"https://swap-api.pump.fun/v2/coins/{m}/trades",p)
        if not d: break
        tr+=d["trades"]
        if not d["pagination"]["hasMore"]: full=True; break
        cur=d["pagination"]["nextCursor"]
    if not full: return None   # can't verify this is the FIRST smart buy
    if not tr: return None
    tr=sorted([t for t in tr if t.get("priceUsd")],key=lambda t:t["slotIndexId"])
    creator=c.get("creator")
    devsold=any(t["userAddress"]==creator and t["type"]=="sell" for t in tr)
    # bundle filter: top-3 wallets' share of buy USD in the first 30 trades must be <= 60%
    eb=collections.Counter()
    for t in tr[:30]:
        if t["type"]=="buy": eb[t["userAddress"]]+=float(t["amountUsd"] or 0)
    tot=sum(eb.values()); conc=sum(v for _,v in eb.most_common(3))/tot if tot else 1
    if conc>0.60 or devsold: return None
    hits=[]
    seen=set()
    for t in tr:
        w=t["userAddress"]
        if t["type"]=="buy" and w in smart and w not in seen and True:
            hits.append((w,sec(t["timestamp"]),float(t["amountUsd"] or 0),float(t["priceUsd"])*1e9))
        if t["type"]=="buy": seen.add(w)
    if not hits or now-hits[0][1]>120: return None   # trigger = first smart buy on this coin, must be fresh
    # leader still holding?
    hold=[h for h in hits if not any(t["userAddress"]==h[0] and t["type"]=="sell" for t in tr)]
    last5=[t for t in tr if now-sec(t["timestamp"])<=300]
    b=sum(float(t["amountUsd"] or 0) for t in last5 if t["type"]=="buy"); s=sum(float(t["amountUsd"] or 0) for t in last5 if t["type"]=="sell")
    buyers=len({t["userAddress"] for t in last5 if t["type"]=="buy"})
    cur_mc=float(tr[-1]['priceUsd'])*1e9
    if devsold or cur_mc>hits[0][3]*1.15 or cur_mc<hits[0][3]*0.85 or False: return None
    dex=dict(profile=False,boosts=0)
    try:
        dp=requests.get("https://api.dexscreener.com/latest/dex/tokens/"+m,timeout=10).json().get("pairs") or []
        for p in dp:
            inf=p.get("info") or {}
            dex["profile"]|=bool(inf.get("header") or inf.get("imageUrl")); dex["boosts"]=max(dex["boosts"],(p.get("boosts") or {}).get("active",0))
    except Exception: pass
    tw=(c.get("twitter") or "").lower()
    social="web/tg" if (c.get("website") or c.get("telegram")) else "x_profile" if tw and "/status/" not in tw else "tweet" if tw else "none"
    return dict(dex=dex,social=social,conc=round(conc,2),trig_mc=round(hits[0][3]),cur_mc=round(cur_mc),mint=m,sym=c.get("symbol"),name=c.get("name"),mc=mc,age_h=(now-c["created_timestamp"]/1000)/3600,devsold=devsold,
                hits=[(w[:6],round(smart[w][0]*100),smart[w][1],round(now-t),round(u),round(mcx)) for w,t,u,mcx in hits],
                holding=len(hold),buy5=round(b),sell5=round(s),buyers5=buyers,complete=c.get("complete"),
                twitter=bool(c.get("twitter")),price=float(tr[-1]["priceUsd"]))
with cf.ThreadPoolExecutor(10) as ex: res=[r for r in ex.map(check,coins.values()) if r]
res.sort(key=lambda r:(-r["holding"],r["devsold"],-(r["buy5"]-r["sell5"])))
json.dump(res,open("live_candidates.json","w"),indent=1)
for r in res[:5]: print(time.strftime('%H:%M:%S'),'PAPER-SIGNAL',r['sym'],r['mint'],'trigger_mc',r['trig_mc'],'now_mc',r['cur_mc'],'age_h',round(r['age_h'],2),'buyers5',r['buyers5'],'net5',r['buy5']-r['sell5'],'leader',r['hits'][0],'conc',r['conc'],'dexprofile',r['dex']['profile'],'boosts',r['dex']['boosts'],'social',r['social'],flush=True)
