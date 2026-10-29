"""One final evaluation of sealed, validation-selected research candidates."""
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader
from sklearn.metrics import confusion_matrix
from deployment.demo_app.real_models import GradeMLP,build_fusion
from deployment.demo_app.tuned_architectures import tree_probabilities
from tools.tune_real_models_gpu import OUT,prepare_grade,fusion_data,transforms,measures,bootstrap,log
from tools.train_real_catscreen_fusion import CatScreenDataset,CLASS_NAMES


def main():
    torch.set_num_threads(3)
    target=OUT/'comparison.json'
    if target.exists():raise RuntimeError('Final results already exist; refusing repeated test evaluation.')
    paths={'grade':OUT/'grade/selected_model.pt','fusion':OUT/'fusion/final_selected_model.pt'}
    sealed={'sealed_at_utc':datetime.now(timezone.utc).isoformat(),'test_predictions_used_for_selection':False,'files':{k:{'path':str(p.relative_to(OUT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for k,p in paths.items()}}
    (OUT/'selection_lock.json').write_text(json.dumps(sealed,indent=2))
    report={'created_at_utc':datetime.now(timezone.utc).isoformat(),'gpu':'NVIDIA GeForce RTX 2050','inference_for_final_metrics':'CPU float32, matching hosted inference','test_policy':'Historical test sets reused once after selections were sealed, not a new external validation. No test predictions were used to select candidates or epochs.','grade':{},'fusion':{}}
    grade=torch.load(paths['grade'],map_location='cpu',weights_only=False)
    model=GradeMLP.create(grade['n_features'],grade['hidden'],grade['dropout']).eval();model.load_state_dict(grade['state_dict'])
    x,y,ids,features,splits=prepare_grade()
    for name,ix in splits.items():
        values=x.iloc[ix].to_numpy(np.float32);filled=np.where(np.isnan(values),np.asarray(grade['medians'],np.float32),values)
        transformed=(filled-np.asarray(grade['means'],np.float32))/np.asarray(grade['stds'],np.float32)
        with torch.inference_mode():neural=model(torch.tensor(transformed,dtype=torch.float32)).softmax(1).numpy()
        weight=grade['tree_weight'];p=(1-weight)*neural+weight*tree_probabilities(grade['tree'],values)
        report['grade'][name]=measures(y[ix],p,True)
        if name=='test':
            report['grade']['test_confusion_matrix']=confusion_matrix(y[ix],p.argmax(1),labels=np.arange(4)).tolist()
            report['grade']['test_accuracy_bootstrap_95ci']=bootstrap(y[ix],p)
        pd.DataFrame({'participant_id':ids.iloc[ix].to_numpy(),'split':name,'target':y[ix],'prediction':p.argmax(1),**{f'p_{i}':p[:,i] for i in range(4)}}).to_csv(OUT/'grade'/f'{name}_predictions.csv',index=False)
    del model
    fusion=torch.load(paths['fusion'],map_location='cpu',weights_only=False);model=build_fusion(fusion).eval();frames,cache=fusion_data()
    for name,key in (('train','train'),('validation','val'),('test','test')):
        ys=[];ps=[]
        with torch.inference_mode():
            for image,ctx,labels in DataLoader(CatScreenDataset(frames[key],cache,transforms()),batch_size=2,shuffle=False,num_workers=0):
                ps.append(model(image,ctx).softmax(1).numpy());ys.extend(labels.numpy())
        fy=np.asarray(ys);p=np.concatenate(ps);report['fusion'][name]=measures(fy,p)
        if name=='test':
            report['fusion']['test_confusion_matrix']=confusion_matrix(fy,p.argmax(1),labels=np.arange(3)).tolist()
            report['fusion']['test_accuracy_bootstrap_95ci']=bootstrap(fy,p,groups=frames[key].id.astype(str).to_numpy())
        pd.DataFrame({'participant_id':frames[key].id.astype(str),'filename':frames[key].filename,'split':name,'target':fy,'prediction':p.argmax(1),**{f'p_{label}':p[:,i] for i,label in enumerate(CLASS_NAMES)}}).to_csv(OUT/'fusion'/f'{name}_predictions.csv',index=False)
    for key,folder in (('grade','cataract_grade_multidata_real'),('fusion','clinical_fusion_catscreen_real')):
        baseline=json.loads((Path('models')/folder/'metrics.json').read_text(encoding='utf-8'))
        (OUT/f'baseline_{key}.json').write_text(json.dumps(baseline,indent=2))
        report[key]['baseline_metrics']=baseline['metrics']
        report[key]['test_accuracy_change_points']=100*(report[key]['test']['accuracy']-baseline['metrics']['test']['accuracy'])
    target.write_text(json.dumps(report,indent=2));log('final_evaluation',results=report)


if __name__=='__main__':main()
