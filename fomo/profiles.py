import json, requests, concurrent.futures as cf, os
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36","Origin":"https://pump.fun","Referer":"https://pump.fun/"}
B="https://frontend-api-v3.pump.fun"
agg=json.load(open("agg.json"))
cands=[w for w,a in agg.items() if a["maxbuy"]<=1000 and a["n"]>=3 and a["dev"]==0]
res=json.load(open("profiles.json")) if os.path.exists("profiles.json") else {}
todo=[w for w in cands if w not in res]
def prof(w):
    out={}
    for per in ("1d","1w"):
        for i in range(2):
            try:
                r=requests.get(f"{B}/portfolio-summary",params=dict(user=w,period=per),headers=H,timeout=8)
                if r.ok: out[per]=r.json(); break
            except Exception: pass
    return w,out
with cf.ThreadPoolExecutor(12) as ex:
    futs=[ex.submit(prof,w) for w in todo]
    for i,f in enumerate(cf.as_completed(futs)):
        w,o=f.result(); res[w]=o
        if i%250==0:
            print(i,len(todo),flush=True); json.dump(res,open("profiles.json","w"))
json.dump(res,open("profiles.json","w")); print("done",len(res),flush=True)
