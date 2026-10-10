"""Live market logger for time-of-day analysis.
Every 2 min: record new launches (created sort). Each coin is revisited 30 min after launch and its first-30-min
tape is saved -> per launch hour: graduation/2x rates, bot share, retail share, after-cost outcomes."""
import json, time, os, requests, threading, collections
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36","Origin":"https://pump.fun","Referer":"https://pump.fun/"}
B="https://frontend-api-v3.pump.fun"; CH="solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
S=requests.Session(); S.headers.update(H)
OUT="live"; os.makedirs(OUT,exist_ok=True)
pending={}   # mint -> created ts
def get(u,p):
    for i in range(3):
        try:
            r=S.get(u,params=p,timeout=15)
            if r.ok: return r.json()
        except Exception: pass
        time.sleep(1+i)
def tape(m,maxpages=20):
    out=[];cur=None
    for _ in range(maxpages):
        p=dict(limit=100,program="pump",chainId=CH)
        if cur: p["cursor"]=cur
        d=get(f"https://swap-api.pump.fun/v2/coins/{m}/trades",p)
        if not d: break
        out+=d["trades"]
        if not d["pagination"]["hasMore"]: break
        cur=d["pagination"]["nextCursor"]
    return out
while True:
    now=time.time()
    for off in range(0,300,50):
        d=get(f"{B}/coins",dict(offset=off,limit=50,sort="created_timestamp",order="DESC",includeNsfw="true")) or []
        for c in d:
            if c["mint"] not in pending and now-c["created_timestamp"]/1000<900:
                pending[c["mint"]]=c
    snap=dict(t=now,launches_15m=sum(1 for c in pending.values() if now-c["created_timestamp"]/1000<900))
    open(f"{OUT}/snapshots.jsonl","a").write(json.dumps(snap)+"\n")
    due=[m for m,c in pending.items() if now-c["created_timestamp"]/1000>=1800]
    for m in due:
        c=pending.pop(m)
        try:
            tr=tape(m)
            open(f"{OUT}/coins.jsonl","a").write(json.dumps(dict(coin={k:c.get(k) for k in ("mint","creator","created_timestamp","name","symbol","twitter","telegram","website")},trades=tr))+"\n")
        except Exception as e: print("err",m,e,flush=True)
    print(time.strftime("%H:%M:%S"),"pending",len(pending),"saved",len(due),flush=True)
    time.sleep(max(5,120-(time.time()-now)))
