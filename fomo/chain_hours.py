"""Hourly launch and graduation counts from Solana RPC (signatures of pump.fun's mint authority and migration account)."""
import requests, time, json, sys
U="https://api.mainnet-beta.solana.com"
ACC={"launch":"TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM","grad":"39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"}
DAYS=float(sys.argv[1]) if len(sys.argv)>1 else 7
def page(addr,before=None):
    p={"limit":1000}
    if before: p["before"]=before
    for i in range(8):
        try:
            d=requests.post(U,json={"jsonrpc":"2.0","id":1,"method":"getSignaturesForAddress","params":[addr,p]},timeout=30).json()
            if "result" in d: return d["result"]
        except Exception: pass
        time.sleep(2*(i+1))
    return None
for name,addr in ACC.items():
    out=open(f"chain_{name}.jsonl","w"); before=None; stop=time.time()-DAYS*86400; n=0
    while True:
        res=page(addr,before)
        if not res: break
        for x in res:
            if x.get("blockTime") and not x["err"]: out.write(json.dumps([x["blockTime"]])+"\n")
        n+=len(res); before=res[-1]["signature"]
        bt=res[-1].get("blockTime") or 0
        if bt<stop: break
        if n%20000==0: print(name,n,time.strftime("%H:%M:%S",time.gmtime(bt)),flush=True)
        time.sleep(1.2)
    out.close(); print("done",name,n,flush=True)
