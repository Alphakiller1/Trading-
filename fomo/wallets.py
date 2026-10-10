# per-wallet behaviour on sub-$80k coins + profile lookup for small-size candidates
def F(x):
    try: return float(x) if x is not None else 0.0
    except Exception: return 0.0
import json, collections, statistics as st, requests, time, concurrent.futures as cf
coins=json.load(open("coins.json")); T={m:[t for t in v if t.get("priceUsd")] for m,v in json.load(open("trades.json")).items()}; sub=json.load(open("sub.json"))
last={}  # last price (mcap) per coin from tape
for m,tr in T.items():
    if tr: last[m]=F(tr[0]["priceUsd"])*1e9
W=collections.defaultdict(lambda: collections.defaultdict(list))
for r in sub: W[r["w"]][r["mint"]].append(r)
# per wallet-coin position (all trades of that wallet on that coin, any mcap, so exits above 80k count)
allw=collections.defaultdict(lambda: collections.defaultdict(list))
for m,tr in T.items():
    for t in tr: allw[t["userAddress"]][m].append(t)
pos=[]
for w,cs in W.items():
    for m in cs:
        tr=sorted(allw[w][m],key=lambda t:t["slotIndexId"])
        buys=[t for t in tr if t["type"]=="buy"]; sells=[t for t in tr if t["type"]=="sell"]
        if not buys: continue
        bu=sum(F(t["amountUsd"]) for t in buys); su=sum(F(t["amountUsd"]) for t in sells)
        bt=sum(F(t["baseAmount"]) for t in buys); stk=sum(F(t["baseAmount"]) for t in sells)
        rem=max(bt-stk,0); mtm=rem*last.get(m,0)/1e9
        first=buys[0]; e_mcap=F(first["priceUsd"])*1e9
        t0=time.mktime(time.strptime(first["timestamp"][:19],"%Y-%m-%dT%H:%M:%S"))
        tl=time.mktime(time.strptime((sells[-1] if sells else first)["timestamp"][:19],"%Y-%m-%dT%H:%M:%S"))
        created=coins.get(m,{}).get("created_timestamp",0)/1000
        pos.append(dict(w=w,mint=m,buy_usd=bu,sell_usd=su,mtm=mtm,pnl=su+mtm-bu,exited=rem<=bt*0.05,
            entry_mcap=e_mcap,age_at_entry=t0-created+time.timezone if created else None,hold=tl-t0,n_buys=len(buys),n_sells=len(sells),
            max_buy=max(F(t["amountUsd"]) for t in buys),dev=coins.get(m,{}).get("creator")==w,ath=max(F(t["priceUsd"]) for t in T[m])*1e9))
json.dump(pos,open("positions.json","w"))
agg=collections.defaultdict(lambda: dict(n=0,pnl=0,buy=0,wins=0,maxbuy=0,trades=0,dev=0))
for p in pos:
    a=agg[p["w"]]; a["n"]+=1; a["pnl"]+=p["pnl"]; a["buy"]+=p["buy_usd"]; a["wins"]+=p["pnl"]>0; a["maxbuy"]=max(a["maxbuy"],p["max_buy"]); a["trades"]+=p["n_buys"]+p["n_sells"]; a["dev"]+=p["dev"]
print("wallets with positions",len(agg))
small=[(w,a) for w,a in agg.items() if a["maxbuy"]<=1000 and a["n"]>=3 and a["dev"]==0]
print("small-size wallets (max buy<=$1k, >=3 coins, not dev):",len(small))
json.dump({w:a for w,a in agg.items()},open("agg.json","w"))
