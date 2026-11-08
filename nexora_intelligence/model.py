def create_model(engine="auto",seed=42,max_iter=300):
    if engine in ("auto","lightgbm"):
        try:
            import lightgbm as lgb
            return lgb.LGBMClassifier(n_estimators=max_iter,learning_rate=.03,num_leaves=15,
              min_child_samples=100,subsample=.8,subsample_freq=1,colsample_bytree=.8,
              reg_lambda=5,random_state=seed,verbosity=-1), "lightgbm"
        except ImportError:
            if engine=="lightgbm": raise
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=max_iter,learning_rate=.03,max_leaf_nodes=15,
      min_samples_leaf=100,l2_regularization=5,early_stopping=False,random_state=seed),"sklearn"
