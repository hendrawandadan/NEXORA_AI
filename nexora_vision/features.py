import numpy as np
import pandas as pd
def build_features(df):
    o,h,l,c=df.open,df.high,df.low,df.close
    v=df.volume if "volume" in df else pd.Series(0,index=df.index)
    pc=c.shift(1); tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False).mean().replace(0,np.nan)
    logc=np.log(c); X=pd.DataFrame(index=df.index)
    for k in [1,2,4,8,16,32,64]: X[f"ret_{k}"]=logc.diff(k)
    X["atr_pct"]=atr/c; X["range_atr"]=(h-l)/atr; X["body_atr"]=(c-o)/atr
    X["upper_wick"]=(h-np.maximum(o,c))/atr; X["lower_wick"]=(np.minimum(o,c)-l)/atr
    delta=c.diff(); up=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean()
    dn=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    X["rsi14"]=100-100/(1+up/dn.replace(0,np.nan))
    for n in [20,50,100,200]:
        X[f"dist_sma{n}"]=(c-c.rolling(n).mean())/atr
        X[f"ema_slope{n}"]=(c.ewm(span=n,adjust=False).mean()-c.ewm(span=n,adjust=False).mean().shift(5))/atr
    lr=logc.diff()
    X["vol20"]=lr.rolling(20).std(); X["vol_ratio"]=X.vol20/lr.rolling(100).std()
    vm=v.rolling(50).mean(); vs=v.rolling(50).std().replace(0,np.nan)
    X["volume_z"]=(v-vm)/vs
    hour=df.ts.dt.hour+df.ts.dt.minute/60
    dow=df.ts.dt.dayofweek
    X["hour_sin"]=np.sin(2*np.pi*hour/24); X["hour_cos"]=np.cos(2*np.pi*hour/24)
    X["dow_sin"]=np.sin(2*np.pi*dow/7); X["dow_cos"]=np.cos(2*np.pi*dow/7)
    if "spread" in df:
        # Spread points are symbol-specific. Keep as a relative rolling feature, not cross-symbol absolute cost.
        sp=pd.to_numeric(df.spread,errors="coerce")
        med=sp.rolling(100,min_periods=20).median().replace(0,np.nan)
        X["spread_relative"]=sp/med
    else:
        X["spread_relative"]=1.0
    X["spread_relative"]=X["spread_relative"].replace([np.inf,-np.inf],np.nan).fillna(1.0)
    return X.replace([np.inf,-np.inf],np.nan)

