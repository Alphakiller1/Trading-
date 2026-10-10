import json, collections, datetime as dt
def load(n): return [json.loads(l)[0] for l in open(f"chain_{n}.jsonl")]
L=load("launch"); G=load("grad")
lo=max(min(L),min(G)) if G else min(L); hi=min(max(L),max(G)) if G else max(L)
L=[t for t in L if lo<=t<=hi]; G=[t for t in G if lo<=t<=hi]
days=(hi-lo)/86400
print(f"window {dt.datetime.utcfromtimestamp(lo)} -> {dt.datetime.utcfromtimestamp(hi)} ({days:.1f} days)  launches {len(L)}  grad txs {len(G)}")
hl=collections.Counter(dt.datetime.utcfromtimestamp(t).hour for t in L)
hg=collections.Counter(dt.datetime.utcfromtimestamp(t).hour for t in G)
print("UTC  ET   launches/hr  grads/hr  grads per 1k launches")
for h in range(24):
    l=hl[h]/days; g=hg[h]/days
    print(f"{h:02d}   {(h-4)%24:02d}   {l:8.0f}   {g:7.1f}   {1000*g/max(l,1):6.1f}")
wd=collections.Counter(dt.datetime.utcfromtimestamp(t).strftime("%a") for t in L); wg=collections.Counter(dt.datetime.utcfromtimestamp(t).strftime("%a") for t in G)
print("by weekday (launches, grads, per1k):",{d:(wd[d],wg[d],round(1000*wg[d]/max(wd[d],1),1)) for d in wd})
