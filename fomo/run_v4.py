import copy4 as C
full={m for m,P in C.PRE.items() if len(P["ts"])<1000}
B=dict(early_conc=0.6,nodev=True,mc_hi=200000)
def go(name,size=100,**kw):
    r=[x for x in C.run(**{**B,**kw,"size":size}) if x["m"] in full]
    print(f"{name:40s} {C.rep(r,size)}",flush=True)
print("== size (fees vs slippage) ==")
for sz in (20,50,100,190,250,500,1000,2000): go(f"size ${sz}",size=sz)
print("== exits ==")
go("mirror (base)")
go("half on leader sell, rest trail 30%",half_mirror=True,rest_trail=0.3)
go("half on leader sell, rest trail 50%",half_mirror=True,rest_trail=0.5)
go("half on leader sell, rest held to 2h",half_mirror=True)
go("mirror, tmax 6h",tmax=6*3600)
go("mirror, stop 50%",stop=0.5)
print("== leader selection ==")
go("leader runner share >= 10%",min_runner=0.10)
go("leader runner share >= 20%",min_runner=0.20)
go("shrinkage score (ROI over buy+$250)",shrink=5)
go("shrinkage score (ROI over buy+$1000)",shrink=20)
go("leader ROI > 25%",min_roi=0.25)
go("confluence 2 leaders in 10 min",conf=2,win=600)
