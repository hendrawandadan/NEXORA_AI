import numpy as np
from sklearn.metrics import accuracy_score,balanced_accuracy_score,roc_auc_score,brier_score_loss,log_loss
def metrics(y,p):
    pred=(p>=.5).astype(int)
    out={"n":int(len(y)),"accuracy":float(accuracy_score(y,pred)),
      "balanced_accuracy":float(balanced_accuracy_score(y,pred)),
      "brier":float(brier_score_loss(y,p)),
      "log_loss":float(log_loss(y,np.clip(p,1e-6,1-1e-6),labels=[0,1])),
      "positive_rate":float(np.mean(y))}
    out["auc"]=float(roc_auc_score(y,p)) if len(np.unique(y))==2 else None
    return out
