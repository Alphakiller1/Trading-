import itertools, json, sys, strategies as S
X0=dict(lat=10,stop=0.20,tp1=0.40,tp1_frac=0.5,trail=0.25,tmax=1800)
cands={
 "launch_30s_<6k":("launch",dict(age=30,lo=0,hi=6000)),
 "launch_60s_6-15k":("launch",dict(age=60,lo=6000,hi=15000)),
 "tws15s_10-40k":("cross",dict(bs=15,vw=20,vm=2.0,lo=10000,hi=40000,minage=600)),
 "tws60s_10-80k_age>1h":("cross",dict(bs=60,vw=20,vm=2.0,lo=10000,hi=80000,minage=3600)),
 "tws60s_20-80k_age>3h":("cross",dict(bs=60,vw=20,vm=2.0,lo=20000,hi=80000,minage=10800)),
 "grad_45k_flow500":("gradzone",dict(cross=45000,flow=500)),
 "grad_55k_flow1000":("gradzone",dict(cross=55000,flow=1000)),
}
exits={"wide":X0,"tight":dict(X0,stop=0.10,tp1=0.20,trail=0.15,tmax=900),"runner":dict(X0,stop=0.30,tp1=1.0,tp1_frac=0.5,trail=0.40,tmax=7200)}
res={}
for name,(kind,P) in cands.items():
    for en,X in exits.items():
        tr=S.evaluate(kind,P,X,half=0); te=S.evaluate(kind,P,X,half=1)
        line={s:(S.report(tr,s),S.report(te,s)) for s in (25,100,250)}
        res[f"{name}|{en}"]=line
        print(f"## {name} | exits={en}"); 
        for s in (25,100,250): print(f"  ${s:<3} TRAIN {line[s][0]}\n       TEST  {line[s][1]}")
        sys.stdout.flush()
json.dump(res,open("strat_results.json","w"),indent=1)
