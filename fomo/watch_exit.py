import requests, time, datetime as dt, sys
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36","Origin":"https://pump.fun","Referer":"https://pump.fun/"}
CH="solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
M,PREFIX,ENTRY=sys.argv[1],sys.argv[2],float(sys.argv[3])
def sec(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
def trades(pages=3):
    out=[];cur=None
    for _ in range(pages):
        p=dict(limit=100,program="pump",chainId=CH)
        if cur: p["cursor"]=cur
        try: d=requests.get(f"https://swap-api.pump.fun/v2/coins/{M}/trades",params=p,headers=H,timeout=15).json()
        except Exception: return out
        out+=d.get("trades",[])
        if not d.get("pagination",{}).get("hasMore"): break
        cur=d["pagination"]["nextCursor"]
    return out
t0=time.time(); leader=None; last_report=0
while time.time()-t0<7200:
    tr=trades(10 if leader is None else 2)
    if leader is None:
        leader=next((t["userAddress"] for t in tr if t["userAddress"].startswith(PREFIX)),None)
        print("leader wallet:",leader,flush=True)
    tr=[t for t in tr if t.get("priceUsd")]
    if tr:
        mc=float(tr[0]["priceUsd"])*1e9
        if any(t["userAddress"]==leader and t["type"]=="sell" for t in tr):
            print(time.strftime("%H:%M:%S"),f"EXIT NOW: leader sold. mcap {mc:,.0f} ({(mc/ENTRY-1)*100:+.0f}% vs entry)",flush=True); break
        if mc<=ENTRY*0.70:
            print(time.strftime("%H:%M:%S"),f"EXIT NOW: stop hit. mcap {mc:,.0f} ({(mc/ENTRY-1)*100:+.0f}%)",flush=True); break
        if time.time()-last_report>=30:
            print(time.strftime("%H:%M:%S"),f"status: mcap {mc:,.0f} ({(mc/ENTRY-1)*100:+.0f}% vs entry), leader still holding",flush=True); last_report=time.time()
    time.sleep(5)
else:
    print("EXIT NOW: 2h time limit",flush=True)
