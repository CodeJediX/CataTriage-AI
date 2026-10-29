"""Additional GPU regularisation comparison, sealed before any final test predictions."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch
from torch.utils.data import DataLoader
from sklearn.model_selection import StratifiedGroupKFold
from deployment.demo_app.tuned_architectures import create_fusion
from tools.tune_real_models_gpu import OUT,SEED,DEVICE,seed,fusion_data,transforms,measures,log
from tools.train_real_catscreen_fusion import CatScreenDataset


@torch.inference_mode()
def vectors(model,frame,cache):
    chunks=[];ys=[]
    for images,ctx,y in DataLoader(CatScreenDataset(frame,cache,transforms()),batch_size=2,shuffle=False,num_workers=0):
        f=model.encoder(images.cuda());f=torch.nn.functional.normalize(f,dim=1)
        chunks.append(torch.cat([f,ctx.cuda()*.15],1));ys.extend(y.numpy())
    return torch.cat(chunks).double(),np.asarray(ys)


def kernel(a,b,gamma):return torch.exp(-gamma*torch.cdist(a,b).square())


def fit(x,y,gamma,regularisation):
    target=torch.nn.functional.one_hot(torch.tensor(y,device=DEVICE),3).double()
    weights=np.sqrt(len(y)/(3*np.bincount(y,minlength=3)))
    target*=torch.tensor(weights,device=DEVICE)
    k=kernel(x,x,gamma)
    return torch.linalg.solve(k+regularisation*torch.eye(len(x),device=DEVICE,dtype=torch.float64),target)


def main():
    torch.set_num_threads(3);seed(SEED)
    frames,cache=fusion_data();base=create_fusion('resnet18',pretrained=True).cuda().eval()
    x,y=vectors(base,frames['train'],cache);v,vy=vectors(base,frames['val'],cache)
    folds=list(StratifiedGroupKFold(3,shuffle=True,random_state=SEED).split(np.arange(len(y)),y,frames['train'].id.astype(str)))
    candidates=[];best=None
    for gamma in (.5,2.,8.):
        for regularisation in (.01,.1,1.):
            scores=[]
            for a,b in folds:
                coef=fit(x[a],y[a],gamma,regularisation)
                p=(kernel(x[b],x[a],gamma)@coef).cpu().numpy();scores.append(measures(y[b],p)['macro_f1'])
            coef=fit(x,y,gamma,regularisation);metric=measures(vy,(kernel(v,x,gamma)@coef).cpu().numpy())
            item={'gamma':gamma,'regularisation':regularisation,'cv_macro_f1':float(np.mean(scores)),'validation':metric,'selection_score':.5*float(np.mean(scores))+.5*metric['macro_f1']}
            candidates.append(item)
            if best is None or item['selection_score']>best[0]:best=(item['selection_score'],item,coef.detach().cpu())
    _,cfg,coef=best
    previous=torch.load(OUT/'fusion/best_model.pt',map_location='cpu',weights_only=False)
    frozen=json.loads((OUT/'fusion/history.json').read_text())
    previous_metric=max([{'macro_f1':r['validation_macro_f1'],'accuracy':r['validation_accuracy']} for r in frozen['head']+frozen['fine_tuning']],key=lambda m:(m['macro_f1'],m['accuracy']))
    # Architecture selection is based on validation; the test set remains unseen.
    use_kernel=(cfg['validation']['macro_f1'],cfg['validation']['accuracy'])>(previous_metric['macro_f1'],previous_metric['accuracy'])
    if use_kernel:
        selected={**previous,'model_type':'CNNKernelContextFusionV2','backbone':'resnet18','state_dict':{k:v.detach().cpu() for k,v in base.encoder.state_dict().items()},'kernel_head':{'centers':x.cpu().float(),'coefficients':coef.float(),'gamma':cfg['gamma'],'regularisation':cfg['regularisation'],'context_scale':.15},'selected':cfg,'phase':'frozen_encoder_gpu_kernel_ridge'}
    else:selected=previous
    torch.save(selected,OUT/'fusion/selected_model.pt')
    (OUT/'fusion/kernel_selection.json').write_text(json.dumps({'protocol':'Nine fixed GPU RBF kernel-ridge heads; train participant-group CV and validation only','candidates':candidates,'kernel_candidate':cfg,'selected_kernel':use_kernel,'previous_validation':previous_metric},indent=2))
    log('fusion_kernel_sealed',selected_kernel=use_kernel,candidate=cfg,previous_validation=previous_metric,test_evaluated=False)


if __name__=='__main__':main()
