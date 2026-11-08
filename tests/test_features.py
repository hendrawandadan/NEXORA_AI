import numpy as np,pandas as pd
from nexora_vision.features import build_features
def test_feature_shape_and_no_future_dependency():
    n=500; rng=np.random.default_rng(1); c=1.1+np.cumsum(rng.normal(0,.0001,n))
    d=pd.DataFrame({"ts":pd.date_range("2020-01-01",periods=n,freq="5min"),
      "open":c,"high":c+.0002,"low":c-.0002,"close":c,"volume":rng.integers(1,100,n)})
    x=build_features(d); assert len(x)==n and "ret_64" in x
