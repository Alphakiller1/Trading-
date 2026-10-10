"""Open-position watcher: status every 15s, alerts for target / stop / momentum breakdown / trailing after +40%."""
import requests, time, datetime as dt, sys
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36","Origin":"https://pump.fun","Referer":"https://pump.fun/"}
CH="solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
M,SYM,ENTRY=sys.argv[1],sys.argv[2],float(sys.argv[3]); TGT,STOP=ENTRY*1.7,ENTRY*0.7
def sec(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
hi=ENTRY; last=0; warned=False; t0=time.time()
while time.time()-t0<7200:
    try:
        tr=[t for t in requests.get(f"https://swap-api.pump.fun/v2/coins/{M}/trades",params=dict(limit=100,program="pump",chainId=CH),headers=H,timeout=10).json()["trades"] if t.get("priceUsd")]
    except Exception: time.sleep(4); continue
    if not tr: time.sleep(4); continue
    now=time.time(); mc=float(tr[0]["priceUsd"])*1e9; hi=max(hi,mc)
    net=sum(float(t["amountUsd"] or 0)*(1 if t["type"]=="buy" else -1) for t in tr if now-sec(t["timestamp"])<=60)
    pct=(mc/ENTRY-1)*100; usd=23*(mc/ENTRY)-23-1.4   # approx $ P&L on $23 after fees
    if mc>=TGT: print(time.strftime("%H:%M:%S"),f"{SYM} TARGET HIT: mcap ${mc:,.0f} ({pct:+.0f}%, ~${usd:+.2f}). SELL",flush=True); break
    if mc<=STOP: print(time.strftime("%H:%M:%S"),f"{SYM} STOP HIT: mcap ${mc:,.0f} ({pct:+.0f}%, ~${usd:+.2f}). SELL",flush=True); break
    if hi>=ENTRY*1.4 and mc<=hi*0.8: print(time.strftime("%H:%M:%S"),f"{SYM} TRAIL: was up {(hi/ENTRY-1)*100:.0f}%, now ${mc:,.0f} ({pct:+.0f}%, ~${usd:+.2f}). SELL to lock profit",flush=True); break
    if net<-500 and not warned: print(time.strftime("%H:%M:%S"),f"{SYM} WARNING: heavy selling ${net:,.0f} in last minute, mcap ${mc:,.0f} ({pct:+.0f}%). Be ready to sell",flush=True); warned=True
    if net>0: warned=False
    if now-last>=15: print(time.strftime("%H:%M:%S"),f"{SYM} ${mc:,.0f} ({pct:+.0f}%, ~${usd:+.2f}) | 1-min flow ${net:+,.0f} | target ${TGT:,.0f} stop ${STOP:,.0f}",flush=True); last=now
    time.sleep(4)
