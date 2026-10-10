import itertools, json, hashlib, statistics as st, sys
import backtest as bt
allt=dict(bt.tapes)
def split(m): return int(hashlib.md5(m.encode()).hexdigest(),16)%2
def score(r):
    if len(r)<15: return None
    return sum(x["pnl"] for x in r)/sum(x["usd"] for x in r)
grid=dict(bs=[5,15,60],vm=[1.5,3.0],stop=[0.03,0.08,0.15],act=[0.05,0.15],trail=[0.05,0.15,0.30],
          band=[(0,20000),(8000,40000),(20000,80000),(0,80000)],usd=[50,100,250])
out=[]
keys=list(grid)
for combo in itertools.product(*grid.values()):
    P=dict(zip(keys,combo)); lo,hi=P.pop("band"); P.update(mc_lo=lo,mc_hi=hi,vw=50 if P["bs"]==5 else 20,tmax=3600*3,lat=3,vt=5)
    bt.tapes={m:t for m,t in allt.items() if split(m)==0}; tr=bt.run(P)
    s=score(tr)
    if s is None: continue
    out.append((s,len(tr),P))
out.sort(key=lambda x:-x[0])
bt.tapes={m:t for m,t in allt.items() if split(m)==1}
res=[]
for s,n,P in out[:25]:
    te=bt.run(P); res.append(dict(train=s,ntrain=n,test=score(te),ntest=len(te),P=P,summ=bt.summ(te)))
json.dump(dict(top=res,ncombos=len(out),dist=[round(x[0],3) for x in out]),open("sweep.json","w"),default=str)
pos=sum(1 for x in out if x[0]>0)
print("combos",len(out),"positive on train",pos)
for r in res[:15]: print(round(r["train"]*100,1),r["ntrain"],"| test",None if r["test"] is None else round(r["test"]*100,1),r["ntest"],{k:r["P"][k] for k in ("bs","vm","stop","act","trail","mc_lo","mc_hi","usd")})
