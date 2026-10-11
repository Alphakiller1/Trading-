import itertools, math, bisect
import early as E
def sim_q(x,d,lat,size,tp,stop,tmax):
    c=x["c"]; tr=x["tr"]; t0=c["created_timestamp"]/1000
    ts=[E.sec(t["timestamp"]) for t in tr]; px=[float(t["priceUsd"]) for t in tr]
    j=bisect.bisect_left(ts,t0+d+lat)
    if j>=len(ts): return None
    pe=px[j]; tok,lift=E.buy(size,pe); pxx=px[-1]
    for i in range(j+1,len(tr)):
        p=px[i]
        if ts[i]-ts[j]<lat: continue
        if p>=pe*(1+tp) or p<=pe*(1-stop) or ts[i]-ts[j]>tmax: pxx=p; break
    return E.sell(tok,pxx*lift)-size
L=E.L; h=len(L)//2; A,Bh=L[:h],L[h:]
grid=list(itertools.product((3,10),(0.15,0.25,0.4,0.6,1.0),(0.15,0.25,0.4),(30,90,300)))
def roi(S,args,size=100):
    r=[v for v in (sim_q(x,args[0],3,size,*args[1:]) for x in S) if v is not None]
    return (sum(r)/size/len(r) if r else -1), len(r)
res=[]
for g in grid:
    a,na=roi(A,g); res.append((a,na,g))
res.sort(key=lambda r:-r[0])
print("best 8 exit rules chosen on EARLIER launches -> tested on LATER launches ($100):")
for a,na,g in res[:8]:
    b,nb=roi(Bh,g)
    print(f" entry +{g[0]}s, take profit +{int(g[1]*100)}%, stop -{int(g[2]*100)}%, max {g[3]}s: earlier {a*100:+5.1f}% (n={na}) -> LATER {b*100:+5.1f}% (n={nb})")
best=res[0][2]
for sz in (25,250,500):
    b,nb=roi(Bh,best,sz); print(f" best rule at ${sz}: later {b*100:+5.1f}%")
