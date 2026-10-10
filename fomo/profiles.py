import json, requests, time, concurrent.futures as cf, sys
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36","Origin":"https://pump.fun","Referer":"https://pump.fun/"}
B="https://frontend-api-v3.pump.fun"; S=requests.Session(); S.headers.update(H)
agg=json.load(open("agg.json"))
cands=[w for w,a in agg.items() if a["maxbuy"]<=1000 and a["n"]>=3 and a["dev"]==0]
def prof(w):
    out={}
    for per in ("1d","1w"):
        for i in range(3):
            try:
                r=S.get(f"{B}/portfolio-summary",params=dict(user=w,period=per),timeout=30)
                if r.ok: out[per]=r.json(); break
            except Exception: pass
            time.sleep(1+i)
    return w,out
res={}
with cf.ThreadPoolExecutor(6) as ex:
    for i,(w,o) in enumerate(ex.map(prof,cands)):
        res[w]=o
        if i%200==0: print(i,len(cands),file=sys.stderr)
json.dump(res,open("profiles.json","w"))
