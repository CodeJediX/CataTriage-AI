"""Validate a fixed legacy/new CNN blend before final testing; no test access."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch
from torch.utils.data import DataLoader
from deployment.demo_app.real_models import build_fusion
from tools.tune_real_models_gpu import OUT,fusion_data,transforms,measures,log
from tools.train_real_catscreen_fusion import CatScreenDataset


def main():
    torch.set_num_threads(3)
    baseline=Path('models/clinical_fusion_catscreen_real/baseline_v1.pt')
    old=torch.load(baseline if baseline.exists() else baseline.with_name('best_model.pt'),map_location='cpu',weights_only=False)
    new=torch.load(OUT/'fusion/selected_model.pt',map_location='cpu',weights_only=False)
    frames,cache=fusion_data();ys=[];probabilities=[]
    for checkpoint in (old,new):
        model=build_fusion(checkpoint).eval();chunks=[]
        with torch.inference_mode():
            for image,ctx,y in DataLoader(CatScreenDataset(frames['val'],cache,transforms()),batch_size=2,shuffle=False,num_workers=0):
                chunks.append(model(image,ctx).softmax(1).numpy())
                if len(probabilities)==0:ys.extend(y.numpy())
        probabilities.append(np.concatenate(chunks));del model
    results=[]
    for weight in (0.,.25,.5,.75,1.):results.append({'secondary_weight':weight,'validation':measures(np.asarray(ys),(1-weight)*probabilities[0]+weight*probabilities[1])})
    best=max(results,key=lambda item:(item['validation']['macro_f1'],item['validation']['accuracy']))
    selected={k:new[k] for k in ('classes','image_size','normalization_mean','normalization_std')}
    selected.update(model_type='FusionBlendV2',model_id='clinical_fusion_catscreen_real_v2' if best['secondary_weight'] else 'clinical_fusion_catscreen_real_v1',primary=old,secondary=new,secondary_weight=best['secondary_weight'],selected=best)
    torch.save(selected,OUT/'fusion/final_selected_model.pt')
    (OUT/'fusion/blend_selection.json').write_text(json.dumps({'selection':'Validation macro-F1 then accuracy; no test predictions','candidates':results,'selected':best},indent=2))
    log('fusion_blend_sealed',selected=best,test_evaluated=False)


if __name__=='__main__':main()
