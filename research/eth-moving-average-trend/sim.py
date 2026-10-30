import json, math
import numpy as np
SYMS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]
H=4*3600*1000
raw={s:dict((t,v) for t,v in json.load(open(f"{s}.json"))) for s in SYMS}
start=max(min(raw[s]) for s in SYMS); end=min(max(raw[s]) for s in SYMS)
T=np.arange(start,end+1,H)
C={}
for s in SYMS:
    c=np.array([raw[s].get(int(t),[np.nan]*5)[3] for t in T])
    # forward-fill gaps
    for i in range(1,len(c)):
        if np.isnan(c[i]): c[i]=c[i-1]
    C[s]=c
R={s:np.r_[0,C[s][1:]/C[s][:-1]-1] for s in SYMS}
YEARS=(T-T[0])/(365.25*86400e3)
def sma(x,n):
    cs=np.cumsum(np.r_[0,x]); out=np.full(len(x),np.nan); out[n-1:]=(cs[n:]-cs[:-n])/n; return out
def rvol(r,n=180):
    out=np.full(len(r),np.nan)
    for i in range(n,len(r)): out[i]=r[i-n+1:i+1].std()
    return out
VOL={s:rvol(R[s]) for s in SYMS}
def signal(s, pairs, longonly=False, band=0.0):
    sig=np.zeros(len(T))
    for f,sl in pairs:
        a=sma(C[s],f); b=sma(C[s],sl); x=np.zeros(len(T)); state=0
        for i in range(len(T)):
            if np.isnan(b[i]): continue
            d=a[i]/b[i]-1
            if d>band: state=1
            elif d<-band: state=-1
            elif band==0: state=0
            x[i]=state
        sig+=x/len(pairs)
    if longonly: sig=np.clip(sig,0,None)
    return sig
def run(pairs=((50,200),), longonly=False, band=0.0, voltarget=None, fee=0.0006, funding=0.0001, warm=400):
    W={}
    for s in SYMS:
        sig=signal(s,pairs,longonly,band)
        if voltarget:
            ann=VOL[s]*math.sqrt(6*365)
            w=sig*np.minimum(1.0, voltarget/ann)
        else: w=sig*1.0
        W[s]=w
    # gross cap 1.0 (same as platform max_gross_leverage scaling)
    G=sum(np.abs(W[s]) for s in SYMS); scale=np.where(G>1,1/np.maximum(G,1e-12),1.0)
    for s in SYMS: W[s]=np.nan_to_num(W[s]*scale)
    eq=np.ones(len(T)); turn=0.0
    port=np.zeros(len(T))
    for i in range(warm+1,len(T)):
        r=0.0
        for s in SYMS:
            w=W[s][i-1]  # decided at close i-1, held over bar i
            r+=w*R[s][i] - abs(w)*0 
            r-= w*funding/2   # 4h bar = half of an 8h funding period
        # trade at close i-1 from drifted weight to new weight (rebalance every bar like adapter)
        tr=0.0
        for s in SYMS:
            prev=W[s][i-2]*(1+R[s][i-1]) if i-2>=0 else 0
            tr+=abs(W[s][i-1]-prev)
        r-=tr*fee; turn+=tr
        port[i]=r
    return T[warm+1:], port[warm+1:], turn
def stats(t,p,a=None,b=None):
    m=np.ones(len(t),bool)
    if a: m&=t>=a
    if b: m&=t<b
    p=p[m]; 
    if len(p)==0: return {}
    eq=np.cumprod(1+p); yrs=len(p)/(6*365.25)
    cagr=eq[-1]**(1/yrs)-1; dd=(eq/np.maximum.accumulate(eq)-1).min()
    sh=p.mean()/p.std()*math.sqrt(6*365.25) if p.std()>0 else 0
    return dict(cagr=round(cagr*100,1), maxdd=round(dd*100,1), sharpe=round(sh,2), calmar=round(cagr/abs(dd),2) if dd<0 else None, total=round((eq[-1]-1)*100,1))
