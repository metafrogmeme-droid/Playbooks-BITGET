import sys, time, calendar; sys.path.insert(0,'.')
from sim import *
ts=lambda s: calendar.timegm(time.strptime(s,'%Y-%m-%d'))*1000
IS=(ts('2021-10-01'),ts('2024-01-01')); OOS=(ts('2024-01-01'),None)
V={
 'V0 baseline 50/200 long+short':dict(),
 'V1 long-only 50/200':dict(longonly=True),
 'V2 20/100':dict(pairs=((20,100),)),
 'V3 100/400':dict(pairs=((100,400),)),
 'V4 ensemble 20/100+50/200+100/400':dict(pairs=((20,100),(50,200),(100,400))),
 'V5 50/200 + 2% band':dict(band=0.02),
 'V6 50/200 + vol target 40%':dict(voltarget=0.40),
 'V7 ensemble + vol target 40%':dict(pairs=((20,100),(50,200),(100,400)),voltarget=0.40),
 'V8 ensemble long-only + vol 40%':dict(pairs=((20,100),(50,200),(100,400)),voltarget=0.40,longonly=True),
}
print(f"{'variant':38s} | {'IS 2021-10..2023 CAGR/DD/Sharpe':32s} | {'OOS 2024..2026-10 CAGR/DD/Sharpe':32s} | full, no funding")
for k,kw in V.items():
    t,p,turn=run(**kw); t0,p0,_=run(funding=0,**kw)
    a=stats(t,p,*IS); b=stats(t,p,*OOS); c=stats(t0,p0,IS[0])
    f=lambda d:f"{d['cagr']:6.1f}% {d['maxdd']:6.1f}% {d['sharpe']:5.2f}"
    print(f"{k:38s} | {f(a):32s} | {f(b):32s} | {f(c)}")
