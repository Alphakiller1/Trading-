"""Auto paper-trader: scan every ~30s with the copy rule, one signal per coin, track each to exit
(leader sells / -30% stop / 2h), log after-cost PnL at $25/$100/$250 to paper_trades.csv."""
import subprocess, threading, time, json, csv, os, sys, re, math, requests, datetime as dt
class bt:   # self-contained cost model (same as backtest.py)
    SOLUSD=110.0; K_DEF=20.27*1.066e9
    @staticmethod
    def fomo_fee(usd): return 0.10 if usd<5 else usd*0.02 if usd<47.5 else 0.95 if usd<190 else usd*0.005
    @staticmethod
    def buy(usd,price_usd,k):
        x=(usd-bt.fomo_fee(usd))*0.99/bt.SOLUSD; p=price_usd/bt.SOLUSD; vS=math.sqrt(p*k); vT=k/vS
        return vT-k/(vS+x)
    @staticmethod
    def sell(tokens,price_usd,k):
        p=price_usd/bt.SOLUSD; vS=math.sqrt(p*k); vT=k/vS; usd=(vS-k/(vT+tokens))*bt.SOLUSD*0.99
        return usd-bt.fomo_fee(usd)
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36","Origin":"https://pump.fun","Referer":"https://pump.fun/"}
CH="solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"; LAT=15
seen=set(); lock=threading.Lock()
LOG="paper_trades.csv"
if not os.path.exists(LOG):
    csv.writer(open(LOG,"w")).writerow(["signal_utc","sym","mint","leader","trigger_mc","entry_mc","exit_mc","why","minutes","ret_pct","pnl25","pnl100","pnl250"])
def sec(s): return dt.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
def latest(m,pages=2):
    out=[];cur=None
    for _ in range(pages):
        p=dict(limit=100,program="pump",chainId=CH)
        if cur: p["cursor"]=cur
        try: d=requests.get(f"https://swap-api.pump.fun/v2/coins/{m}/trades",params=p,headers=H,timeout=15).json()
        except Exception: return out
        out+=d.get("trades",[])
        if not d.get("pagination",{}).get("hasMore"): break
        cur=d["pagination"]["nextCursor"]
    return [t for t in out if t.get("priceUsd")]
def pnl(size,pe,px):
    k=bt.K_DEF; tok=bt.buy(size,pe/1e9,k); x=(size-bt.fomo_fee(size))*0.99/bt.SOLUSD
    vS=math.sqrt(pe/1e9/bt.SOLUSD*k); lift=((vS+x)/vS)**2
    return round(bt.sell(tok,px/1e9*lift,k)-size,2)
def track(sig):
    m=sig["mint"]; time.sleep(LAT)
    tr=latest(m,10); leader=next((t["userAddress"] for t in tr if t["userAddress"].startswith(sig["leader"])),None)
    if not tr: return
    entry=float(tr[0]["priceUsd"])*1e9; t0=time.time(); why="time"; ex=entry
    while time.time()-t0<7200:
        time.sleep(5)
        tr=latest(m)
        if not tr: continue
        ex=float(tr[0]["priceUsd"])*1e9
        if any(t["userAddress"]==leader and t["type"]=="sell" for t in tr): why="leader_sold"; break
        if ex<=entry*0.7: why="stop"; break
    time.sleep(LAT if why!="stop" else 0)
    tr=latest(m,1); ex=float(tr[0]["priceUsd"])*1e9 if tr else ex
    row=[sig["t"],sig["sym"],m,leader,sig["trig"],round(entry),round(ex),why,round((time.time()-t0)/60,1),round((ex/entry-1)*100,1),pnl(25,entry,ex),pnl(100,entry,ex),pnl(250,entry,ex)]
    with lock: csv.writer(open(LOG,"a")).writerow(row)
    print(f"[paper] {sig['sym']} closed: {why}, {row[9]:+.1f}% in {row[8]} min | $100 trade: {row[11]:+.2f}",flush=True)
pat=re.compile(r"PAPER-SIGNAL (\S+) (\S+) trigger_mc (\d+) now_mc (\d+) .* leader \('(\w+)'")
while True:
    try: out=subprocess.run(["python3","watch_once.py"],capture_output=True,text=True,timeout=110).stdout
    except Exception: out=""
    for l in out.splitlines():
        mt=pat.search(l)
        if not mt: continue
        sym,m,trig,now,lead=mt.groups()
        if m in seen: continue
        seen.add(m)
        print(f"[paper] OPEN {sym} {m} trigger {int(trig):,} now {int(now):,} leader {lead}",flush=True)
        threading.Thread(target=track,args=(dict(t=time.strftime("%H:%M:%S"),sym=sym,mint=m,trig=int(trig),leader=lead),),daemon=True).start()
    time.sleep(20)
