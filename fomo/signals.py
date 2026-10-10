"""Pre-entry BUY/WAIT/AVOID signals for one coin. Prints only when the state changes."""
import requests, time, datetime as dt, sys
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36","Origin":"https://pump.fun","Referer":"https://pump.fun/"}
CH="solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
M,SYM=sys.argv[1],sys.argv[2]; DIP,BRK,FLOOR=float(sys.argv[3]),float(sys.argv[4]),float(sys.argv[5])
def sec(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
state=None; t0=time.time()
while time.time()-t0<3600:
    try:
        d=requests.get(f"https://swap-api.pump.fun/v2/coins/{M}/trades",params=dict(limit=100,program="pump",chainId=CH),headers=H,timeout=10).json()
        tr=[t for t in d["trades"] if t.get("priceUsd")]
    except Exception: time.sleep(4); continue
    if not tr: time.sleep(4); continue
    now=time.time(); mc=float(tr[0]["priceUsd"])*1e9
    l1=[t for t in tr if now-sec(t["timestamp"])<=60]
    net=sum(float(t["amountUsd"] or 0)*(1 if t["type"]=="buy" else -1) for t in l1)
    if mc<FLOOR or net<-500: new="AVOID"
    elif mc<=DIP and net>0: new="BUY (dip)"
    elif mc>=BRK and net>=300: new="BUY (breakout)"
    else: new="WAIT"
    if new!=state:
        msg={"AVOID":"don't buy, breaking down","WAIT":"no entry yet","BUY (dip)":"entry OK, buyers stepping in on the dip","BUY (breakout)":"entry OK, momentum breakout"}[new]
        print(time.strftime("%H:%M:%S"),f"{SYM} {new}: mcap ${mc:,.0f}, 1-min net flow ${net:+,.0f} ({msg}). Stop if bought: ${mc*0.7:,.0f}",flush=True)
        state=new
    time.sleep(4)
