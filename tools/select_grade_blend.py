"""Select a fixed neural/tree blend using validation predictions only."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch
from deployment.demo_app.real_models import GradeMLP
from deployment.demo_app.tuned_architectures import tree_probabilities
from tools.tune_real_models_gpu import prepare_grade,OUT,measures,log


def main():
    x,y,ids,features,splits=prepare_grade()
    baseline=Path('models/cataract_grade_multidata_real/baseline_v1.pt')
    neural=torch.load(baseline if baseline.exists() else baseline.with_name('best_model.pt'),map_location='cpu',weights_only=False)
    tree=torch.load(OUT/'grade/best_model.pt',map_location='cpu',weights_only=False)
    assert neural['features']==tree['features']==features
    model=GradeMLP.create(neural['n_features'],neural['hidden'],neural['dropout']).cuda().eval();model.load_state_dict(neural['state_dict'])
    val=x.iloc[splits['validation']].to_numpy(np.float32); filled=np.where(np.isnan(val),np.asarray(neural['medians'],np.float32),val)
    transformed=(filled-np.asarray(neural['means'],np.float32))/np.asarray(neural['stds'],np.float32)
    with torch.inference_mode():p_neural=model(torch.tensor(transformed,dtype=torch.float32,device='cuda')).softmax(1).cpu().numpy()
    p_tree=tree_probabilities(tree,val);results=[]
    for weight in (0.,.25,.5,.75,1.):
        metric=measures(y[splits['validation']],(1-weight)*p_neural+weight*p_tree,True)
        results.append({'tree_weight':weight,'validation':metric})
    best=max(results,key=lambda v:(v['validation']['macro_f1'],v['validation']['accuracy']))
    selected={**neural,'model_type':'GradeBlendV2','model_id':'cataract_grade_multidata_real_v2' if best['tree_weight'] else 'cataract_grade_multidata_real_v1','tree':tree,'tree_weight':best['tree_weight'],'selected':best,'validation_blends':results}
    torch.save(selected,OUT/'grade/selected_model.pt')
    (OUT/'grade/blend_selection.json').write_text(json.dumps({'selection':'Validation macro-F1 then accuracy; no test predictions','candidates':results,'selected':best},indent=2))
    log('grade_blend_sealed',selected=best,test_evaluated=False)


if __name__=='__main__':main()
