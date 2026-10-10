import json, collections, statistics as st, datetime as dt
def F(x):
    try: return float(x) if x is not None else 0.0
    except Exception: return 0.0
coins=json.load(open("coins.json")); T={m:[t for t in v if t.get("priceUsd")] for m,v in json.load(open("trades.json")).items()}
def ts(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
rows=[]
for m,tr in T.items():
    c=coins.get(m,{}); creator=c.get("creator")
    for t in tr:
        p=F(t["priceUsd"]); usd=F(t["amountUsd"]); sol=F(t["amountSol"])
        rows.append(dict(mint=m,w=t["userAddress"],side=t["type"],t=ts(t["timestamp"]),mcap=p*1e9,usd=usd,sol=sol,tok=F(t["baseAmount"]),prog=t["program"],dev=t["userAddress"]==creator,created=c.get("created_timestamp",0)/1000))
print("trades",len(rows),"coins",len(T))
sub=[r for r in rows if r["mcap"]<80000]
print("sub80k trades",len(sub), "programs",collections.Counter(r["prog"] for r in sub).most_common(4))
# coin outcomes
for m in T:
    pass
ath={m:max([r["mcap"] for r in rows if r["mint"]==m] or [0]) for m in T}
b=collections.Counter()
for m,a in ath.items():
    b["<10k" if a<1e4 else "10-30k" if a<3e4 else "30-80k" if a<8e4 else "80k-300k" if a<3e5 else ">300k"]+=1
print("coin ATH buckets (sampled tape)",b)
by=collections.defaultdict(list)
for r in sub: by[r["w"]].append(r)
json.dump(sub,open("sub.json","w"))
sizes=[r["usd"] for r in sub if r["side"]=="buy"]
print("buy size pct", [round(sorted(sizes)[int(len(sizes)*q)],1) for q in (.1,.25,.5,.75,.9,.99)])
print("wallets",len(by))
