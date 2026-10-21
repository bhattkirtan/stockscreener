#!/usr/bin/env python3
"""Evaluate backtest runs with in-sample / out-of-sample split + cost sensitivity."""
import pandas as pd, numpy as np, glob, os, sys, json

def metrics(d):
    if len(d)==0: return None
    W=d.pnl[d.pnl>0]; L=d.pnl[d.pnl<0]
    if len(W)==0 or len(L)==0: return None
    be=abs(L.mean())/(W.mean()+abs(L.mean()))*100
    wr=len(W)/len(d)*100
    eq=d.pnl.cumsum(); dd=(eq-eq.cummax()).min()
    return dict(n=len(d), wr=round(wr,2), beWR=round(be,2), gap=round(wr-be,2),
        PF=round(W.sum()/-L.sum(),3), pnl=round(d.pnl.sum()),
        exp=round(d.pnl.mean(),2), maxDD=round(dd))

def evaluate(path, label):
    f=os.path.join(path,'trades.csv')
    if not os.path.exists(f): return None
    d=pd.read_csv(f)
    d=d[d.status=='CLOSED'].copy()
    if len(d)<30: return None
    d['entry_time']=pd.to_datetime(d.entry_time)
    d=d.sort_values('entry_time')
    mid=d.entry_time.min()+(d.entry_time.max()-d.entry_time.min())/2
    full=metrics(d); IS=metrics(d[d.entry_time<mid]); OOS=metrics(d[d.entry_time>=mid])
    if not full: return None
    row=dict(run=label, n=full['n'], WR=full['wr'], gap=full['gap'], PF=full['PF'],
             pnl=full['pnl'], maxDD=full['maxDD'])
    row['IS_PF']  = IS['PF']  if IS else None
    row['OOS_PF'] = OOS['PF'] if OOS else None
    row['IS_gap'] = IS['gap'] if IS else None
    row['OOS_gap']= OOS['gap'] if OOS else None
    # both-halves-positive test
    row['stable'] = bool(IS and OOS and IS['PF']>1.0 and OOS['PF']>1.0)
    return row

if __name__=='__main__':
    roots=sys.argv[1:] or ['/tmp/sweep']
    rows=[]
    for root in roots:
        for p in sorted(glob.glob(os.path.join(root,'*','*'))):
            if os.path.isdir(p):
                r=evaluate(p, os.path.basename(p))
                if r: rows.append(r)
    if not rows: print("no runs"); sys.exit()
    df=pd.DataFrame(rows).sort_values('PF',ascending=False)
    pd.set_option('display.width',250)
    print(df.to_string(index=False))
