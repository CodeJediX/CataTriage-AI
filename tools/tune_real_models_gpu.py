"""Bounded GPU tuning with immutable original splits and a single final test evaluation.

No test predictions are computed during candidate selection. Raw datasets are read-only.
All new artifacts remain in models/tuning_20261030 until explicitly promoted.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('TORCH_HOME', str(ROOT/'.build-cache/torch'))
os.environ.setdefault('MPLBACKEND', 'Agg')
import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader
from torchvision.transforms import v2
from sklearn.model_selection import train_test_split, StratifiedKFold, StratifiedGroupKFold
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, confusion_matrix, cohen_kappa_score, mean_absolute_error
from deployment.demo_app.tuned_architectures import tabular_features, tree_probabilities, create_fusion
from tools.train_real_multidata_model import build_dataset, SEED as ORIGINAL_SEED
from tools.train_real_catscreen_fusion import locate_release, CatScreenDataset, encode_context, LABEL_MAP, CLASS_NAMES

OUT = ROOT/'models/tuning_20261030'
SEED = 20261030
DEVICE = torch.device('cuda')


def log(event, **data):
    item = {'time_utc': datetime.now(timezone.utc).isoformat(), 'event': event, **data}
    with (OUT/'progress.jsonl').open('a', encoding='utf-8') as f: f.write(json.dumps(item)+'\n')
    print(json.dumps(item), flush=True)


def seed(value):
    random.seed(value); np.random.seed(value); torch.manual_seed(value); torch.cuda.manual_seed_all(value)


def measures(y, probabilities, ordinal=False):
    pred = np.asarray(probabilities).argmax(1)
    result = {'accuracy':float(accuracy_score(y,pred)), 'balanced_accuracy':float(balanced_accuracy_score(y,pred)), 'macro_f1':float(f1_score(y,pred,average='macro',zero_division=0))}
    cm = confusion_matrix(y,pred,labels=np.arange(probabilities.shape[1]))
    result['per_class_recall'] = (cm.diagonal()/np.maximum(cm.sum(1),1)).tolist()
    if ordinal:
        result.update(quadratic_weighted_kappa=float(cohen_kappa_score(y,pred,weights='quadratic')), grade_mae=float(mean_absolute_error(y,pred)))
    return result


def score(metric): return (metric['macro_f1'], metric['accuracy'])


def clone(model): return {k:v.detach().cpu().clone() for k,v in model.state_dict().items()}


def prepare_grade():
    x,y,ids,features = build_dataset()
    index = np.arange(len(y))
    tr,te = train_test_split(index,test_size=.15,stratify=y,random_state=ORIGINAL_SEED)
    tr,va = train_test_split(tr,test_size=.1764705882,stratify=y.iloc[tr],random_state=ORIGINAL_SEED)
    splits = {'train':tr,'validation':va,'test':te}
    old = pd.read_csv(ROOT/'models/cataract_grade_multidata_real/predictions_and_splits.csv',dtype={'participant_id':str})
    for name,ix in splits.items():
        assert set(ids.iloc[ix].astype(str)) == set(old.loc[old.split==name,'participant_id'])
    assert not ids.duplicated().any()
    return x,y.to_numpy(),ids,features,splits


def train_grade():
    from catboost import CatBoostClassifier
    folder=OUT/'grade';folder.mkdir(exist_ok=True)
    x,y,ids,features,splits=prepare_grade(); tr=splits['train'];va=splits['validation']
    raw=x.to_numpy(np.float32)
    configs=[{'depth':depth,'l2_leaf_reg':l2,'balanced':balanced} for depth,l2,balanced in ((4,8,False),(5,12,False),(6,16,False),(4,8,True),(5,12,True),(6,16,True))]
    folds=list(StratifiedKFold(3,shuffle=True,random_state=SEED).split(tr,y[tr]))
    leaderboard=[];best=None
    for run,cfg in enumerate(configs):
        cv=[];iterations=[]
        for fold,(a,b) in enumerate(folds):
            a,b=tr[a],tr[b]; med=np.nanmedian(raw[a],axis=0); med=np.nan_to_num(med)
            weights=np.sqrt(len(a)/(4*np.bincount(y[a],minlength=4))) if cfg['balanced'] else None
            model=CatBoostClassifier(iterations=1400,depth=cfg['depth'],learning_rate=.035,l2_leaf_reg=cfg['l2_leaf_reg'],loss_function='MultiClass',eval_metric='MultiClass',task_type='GPU',devices='0',gpu_ram_part=.45,random_seed=SEED+fold,thread_count=4,allow_writing_files=False,class_weights=weights,verbose=False)
            model.fit(tabular_features(raw[a],med),y[a],eval_set=(tabular_features(raw[b],med),y[b]),early_stopping_rounds=100)
            metric=measures(y[b],model.predict_proba(tabular_features(raw[b],med)),True)
            cv.append(metric);iterations.append(model.tree_count_)
            log('grade_cv',run=run,fold=fold,trees=model.tree_count_,validation=metric)
        med=np.nan_to_num(np.nanmedian(raw[tr],axis=0));weights=np.sqrt(len(tr)/(4*np.bincount(y[tr],minlength=4))) if cfg['balanced'] else None
        # Epoch/tree count is determined from training-only folds, not the final test.
        n=max(80,int(np.median(iterations)))
        model=CatBoostClassifier(iterations=n,depth=cfg['depth'],learning_rate=.035,l2_leaf_reg=cfg['l2_leaf_reg'],loss_function='MultiClass',task_type='GPU',devices='0',gpu_ram_part=.45,random_seed=SEED,thread_count=4,allow_writing_files=False,class_weights=weights,verbose=False)
        model.fit(tabular_features(raw[tr],med),y[tr])
        vm=measures(y[va],model.predict_proba(tabular_features(raw[va],med)),True)
        cvf=float(np.mean([m['macro_f1'] for m in cv])); selection=.5*cvf+.5*vm['macro_f1']
        record={'run':run,'config':cfg,'trees':n,'cv_macro_f1':cvf,'validation':vm,'selection_score':selection}
        leaderboard.append(record);(folder/'leaderboard.json').write_text(json.dumps(leaderboard,indent=2))
        log('grade_candidate',**record)
        if best is None or selection>best[0]: best=(selection,model,med,record)
    _,model,med,record=best
    model.save_model(str(folder/'best_model.cbm')); model.save_model(str(folder/'tree_export.json'),format='json')
    exported=json.loads((folder/'tree_export.json').read_text()); trees=[]
    for tree in exported['oblivious_trees']:
        assert all(s['split_type']=='FloatFeature' for s in tree['splits'])
        trees.append({'features':[s['float_feature_index'] for s in tree['splits']],'borders':[s['border'] for s in tree['splits']],'values':np.asarray(tree['leaf_values']).reshape(-1,4).tolist()})
    saved={'model_type':'CatBoostObliviousEnsembleV2','model_id':'cataract_grade_multidata_real_v2','features':features,'medians':med.tolist(),'labels':['grade 0','grade 1','grade 2','grade 3+'],'trees':trees,'tree_scale':exported['scale_and_bias'][0],'tree_bias':exported['scale_and_bias'][1],'selected':record}
    # Validate dependency-free hosted inference against CatBoost, including missing inputs.
    probe=np.concatenate([raw[tr[:40]],np.full((1,raw.shape[1]),np.nan,dtype=np.float32)])
    error=float(np.abs(tree_probabilities(saved,probe)-model.predict_proba(tabular_features(probe,med))).max())
    assert error<1e-6,error
    saved['export_max_probability_error']=error
    torch.save(saved,folder/'best_model.pt')
    log('grade_selected',selected=record,export_error=error,test_evaluated=False)
    return saved,(raw,y,ids,splits)


def transforms(augment=False):
    steps=[v2.Resize((224,224))]
    if augment: steps += [v2.RandomAffine(5,translate=(.025,.025),scale=(.96,1.04)),v2.ColorJitter(.08,.08,.06,0)]
    return v2.Compose(steps+[v2.ToImage(),v2.ToDtype(torch.float32,scale=True),v2.Normalize([.485,.456,.406],[.229,.224,.225])])


def fusion_data():
    image_dir,files=locate_release();frames={k:pd.read_excel(v) for k,v in files.items()}
    for a,b in (('train','val'),('train','test'),('val','test')):
        assert not set(frames[a].id.astype(str)) & set(frames[b].id.astype(str))
    cache=Path(r'E:\Eye Project\data sets\CatScreen_Public_Sample\training_cache_512')
    assert all((cache/str(name)).exists() for f in frames.values() for name in f.filename)
    fingerprints={}
    for split,frame in frames.items():
        for name in frame.filename:
            digest=hashlib.sha256((cache/str(name)).read_bytes()).hexdigest()
            if digest in fingerprints: assert fingerprints[digest]==split,'Cross-split duplicate image'
            fingerprints[digest]=split
    return frames,cache


@torch.inference_mode()
def extract(model,frame,cache,augment=False):
    model.eval(); chunks=[]
    loader=DataLoader(CatScreenDataset(frame,cache,transforms(augment)),batch_size=12,shuffle=False,num_workers=0)
    for image,_,_ in loader: chunks.append(model.encoder(image.to(DEVICE)).detach())
    return torch.cat(chunks)


def head_fit(model,features,contexts,y,train_index,valid_index,iterations=140,early_stop=False):
    for p in model.encoder.parameters(): p.requires_grad=False
    optimizer=torch.optim.AdamW(list(model.head.parameters())+list(model.context.parameters()),lr=.002,weight_decay=.025)
    a=torch.tensor(train_index,device=DEVICE);b=torch.tensor(valid_index,device=DEVICE)
    counts=torch.bincount(y[a],minlength=3);weights=torch.sqrt(len(a)/(3*counts.float()))
    lossfn=nn.CrossEntropyLoss(weight=weights,label_smoothing=.02)
    best=None;history=[];stale=0
    for epoch in range(iterations):
        model.train(); optimizer.zero_grad(set_to_none=True)
        chosen=features[a,epoch%features.shape[1]]
        logits=model.from_features(chosen,contexts[a]);loss=lossfn(logits,y[a]);loss.backward();optimizer.step()
        if (epoch+1)%5 and epoch!=iterations-1: continue
        model.eval()
        with torch.no_grad():
            p=model.from_features(features[b,0],contexts[b]).softmax(1).cpu().numpy()
            train_p=model.from_features(features[a,0],contexts[a]).softmax(1).cpu().numpy()
        vm=measures(y[b].cpu().numpy(),p);tm=measures(y[a].cpu().numpy(),train_p)
        history.append({'epoch':epoch+1,'train_loss':loss.item(),'train_accuracy':tm['accuracy'],'validation_accuracy':vm['accuracy'],'validation_macro_f1':vm['macro_f1']})
        if early_stop and (best is None or score(vm)>best[0]): best=(score(vm),clone(model),vm);stale=0
        else: stale+=1
        if early_stop and epoch>=60 and stale>=12: break
    if early_stop: model.load_state_dict(best[1]);vm=best[2]
    return vm,history


def train_fusion():
    folder=OUT/'fusion';folder.mkdir(exist_ok=True);frames,cache=fusion_data()
    train=frames['train']; val=frames['val']; combined=pd.concat([train,val],ignore_index=True)
    contexts=torch.tensor(np.stack([encode_context(row) for _,row in combined.iterrows()]),device=DEVICE)
    y=torch.tensor(combined.diagnosis.str.lower().map(LABEL_MAP).to_numpy(),dtype=torch.long,device=DEVICE)
    folds=list(StratifiedGroupKFold(3,shuffle=True,random_state=SEED).split(np.arange(len(train)),y[:len(train)].cpu().numpy(),train.id.astype(str)))
    leaderboard=[];best=None
    resumed='--resume' in sys.argv and (folder/'leaderboard.json').exists()
    previous=json.loads((folder/'leaderboard.json').read_text()) if resumed else []
    chosen=max(previous,key=lambda x:(x['cv_macro_f1'],x['cv_accuracy'])) if previous else None
    for backbone in ([chosen['backbone']] if chosen else ('mobilenet_v3_small','efficientnet_b0','resnet18')):
        seed(SEED);model=create_fusion(backbone,pretrained=True).to(DEVICE)
        features=torch.stack([extract(model,combined,cache,augment=bool(view)) for view in range(3)],dim=1)
        if chosen:
            best=((chosen['cv_macro_f1'],chosen['cv_accuracy']),chosen,features.detach().cpu(),clone(model))
            del model,features;torch.cuda.empty_cache();break
        for hidden,dropout in ((0,.35),(64,.5)):
            fold_metrics=[]
            for fold,(a,b) in enumerate(folds):
                seed(SEED+fold);candidate=create_fusion(backbone,hidden,dropout).to(DEVICE)
                metric,_=head_fit(candidate,features,contexts,y,a,b)
                fold_metrics.append(metric)
                log('fusion_feature_cv',backbone=backbone,hidden=hidden,fold=fold,validation=metric)
                del candidate
            cvf=float(np.mean([m['macro_f1'] for m in fold_metrics]));cva=float(np.mean([m['accuracy'] for m in fold_metrics]))
            entry={'backbone':backbone,'hidden':hidden,'dropout':dropout,'cv_macro_f1':cvf,'cv_accuracy':cva}
            leaderboard.append(entry);(folder/'leaderboard.json').write_text(json.dumps(leaderboard,indent=2))
            if best is None or (cvf,cva)>best[0]: best=((cvf,cva),entry,features.detach().cpu(),clone(model))
        del model,features;torch.cuda.empty_cache()
    _,cfg,features,encoder_state=best;seed(SEED)
    model=create_fusion(cfg['backbone'],cfg['hidden'],cfg['dropout']).to(DEVICE)
    # Transfer only pretrained encoder parameters; head dimensions may differ.
    model.encoder.load_state_dict({k.removeprefix('encoder.'):v for k,v in encoder_state.items() if k.startswith('encoder.')})
    features=features.to(DEVICE);a=np.arange(len(train));b=np.arange(len(train),len(combined))
    frozen_metric,history=head_fit(model,features,contexts,y,a,b,iterations=300,early_stop=True)
    best_metric=frozen_metric;best_state=clone(model);phase='frozen_encoder';best_epoch=0
    log('fusion_architecture_selected',config=cfg,frozen_validation=frozen_metric,test_evaluated=False)
    torch.save({'state_dict':best_state,'config':cfg,'metric':best_metric,'history':history},folder/'frozen_checkpoint.pt')
    del features;torch.cuda.empty_cache()
    for p in model.encoder.parameters():p.requires_grad=False
    last=model.encoder.layer4 if cfg['backbone']=='resnet18' else model.encoder.features[-3:]
    for p in last.parameters():p.requires_grad=True
    optimizer=torch.optim.SGD([{'params':last.parameters(),'lr':5e-4},{'params':model.context.parameters(),'lr':2e-3},{'params':model.head.parameters(),'lr':2e-3}],momentum=.9,weight_decay=.0005,foreach=False)
    loader=DataLoader(CatScreenDataset(train,cache,transforms(True)),batch_size=4,shuffle=True,num_workers=0,generator=torch.Generator().manual_seed(SEED))
    val_loader=DataLoader(CatScreenDataset(val,cache,transforms()),batch_size=2,shuffle=False,num_workers=0)
    train_eval=DataLoader(CatScreenDataset(train,cache,transforms()),batch_size=2,shuffle=False,num_workers=0)
    counts=np.bincount(train.diagnosis.str.lower().map(LABEL_MAP),minlength=3);weights=torch.tensor(np.sqrt(len(train)/(3*counts)),dtype=torch.float32,device=DEVICE)
    lossfn=nn.CrossEntropyLoss(weight=weights,label_smoothing=.02);scaler=torch.amp.GradScaler('cuda');stale=0;fine_history=[]
    for epoch in range(24):
        model.train()
        # Tiny batches must not overwrite pretrained BatchNorm running statistics.
        for module in model.encoder.modules():
            if isinstance(module,nn.modules.batchnorm._BatchNorm):module.eval()
        losses=[]
        for images,ctx,target in loader:
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast('cuda',dtype=torch.float16): loss=lossfn(model(images.to(DEVICE),ctx.to(DEVICE)),target.to(DEVICE))
            scaler.scale(loss).backward();scaler.unscale_(optimizer);nn.utils.clip_grad_norm_(model.parameters(),2.);scaler.step(optimizer);scaler.update();losses.append(loss.item())
        del images,ctx,target,loss
        torch.cuda.empty_cache()
        vm,_,_=eval_fusion(model,val_loader);tm,_,_=eval_fusion(model,train_eval)
        item={'epoch':epoch+1,'train_loss':float(np.mean(losses)),'train_accuracy':tm['accuracy'],'validation_accuracy':vm['accuracy'],'validation_macro_f1':vm['macro_f1']};fine_history.append(item)
        if score(vm)>score(best_metric):best_metric=vm;best_state=clone(model);best_epoch=epoch+1;phase='fine_tuned';stale=0
        else:stale+=1
        log('fusion_finetune',**item,best_validation=best_metric)
        if epoch>=9 and stale>=9:break
    model.load_state_dict(best_state)
    saved={'model_type':'CNNContextFusionV2','model_id':'clinical_fusion_catscreen_real_v2','state_dict':best_state,'backbone':cfg['backbone'],'hidden':cfg['hidden'],'dropout':cfg['dropout'],'classes':CLASS_NAMES,'image_size':224,'normalization_mean':[.485,.456,.406],'normalization_std':[.229,.224,.225],'selected':cfg,'phase':phase,'best_epoch':best_epoch,'source':'CatScreen official public sample'}
    torch.save(saved,folder/'best_model.pt');(folder/'history.json').write_text(json.dumps({'head':history,'fine_tuning':fine_history},indent=2))
    log('fusion_selected',config=cfg,phase=phase,validation=best_metric,test_evaluated=False)
    return model,saved,frames,cache


@torch.inference_mode()
def eval_fusion(model,loader):
    model.eval();ys=[];ps=[]
    for images,ctx,y in loader:
        with torch.autocast('cuda',dtype=torch.float16):prob=model(images.to(DEVICE),ctx.to(DEVICE)).softmax(1)
        ps.append(prob.float().cpu().numpy());ys.extend(y.numpy())
    probabilities=np.concatenate(ps);y=np.asarray(ys)
    return measures(y,probabilities),y,probabilities


def bootstrap(y,p,seed_value=SEED,groups=None):
    rng=np.random.default_rng(seed_value);values=[]
    for _ in range(2000):
        if groups is None: ix=rng.integers(0,len(y),size=len(y))
        else:
            unique=np.unique(groups);sample=rng.choice(unique,len(unique),replace=True)
            ix=np.concatenate([np.flatnonzero(groups==group) for group in sample])
        values.append(float((p[ix].argmax(1)==y[ix]).mean()))
    return [float(x) for x in np.quantile(values,[.025,.975])]


def final_evaluation(grade,grade_data,model,fusion,frames,cache):
    # This is the first and only test-prediction stage; both selections already exist on disk.
    report={'created_at_utc':datetime.now(timezone.utc).isoformat(),'gpu':torch.cuda.get_device_name(0),'seed':SEED,'test_policy':'Original historical test sets reused once for final comparison; not a new external validation. No candidate/epoch selection used test predictions.','grade':{},'fusion':{}}
    raw,y,ids,splits=grade_data
    for name,ix in splits.items():
        p=tree_probabilities(grade,raw[ix]);report['grade'][name]=measures(y[ix],p,True)
        if name=='test':report['grade']['test_confusion_matrix']=confusion_matrix(y[ix],p.argmax(1),labels=np.arange(4)).tolist();report['grade']['test_accuracy_bootstrap_95ci']=bootstrap(y[ix],p)
        pd.DataFrame({'participant_id':ids.iloc[ix].to_numpy(),'split':name,'target':y[ix],'prediction':p.argmax(1),**{f'p_{i}':p[:,i] for i in range(4)}}).to_csv(OUT/'grade'/f'{name}_predictions.csv',index=False)
    for name,key in (('train','train'),('validation','val'),('test','test')):
        loader=DataLoader(CatScreenDataset(frames[key],cache,transforms()),batch_size=2,shuffle=False,num_workers=0)
        metric,fy,p=eval_fusion(model,loader);report['fusion'][name]=metric
        if name=='test':report['fusion']['test_confusion_matrix']=confusion_matrix(fy,p.argmax(1),labels=np.arange(3)).tolist();report['fusion']['test_accuracy_bootstrap_95ci']=bootstrap(fy,p,groups=frames[key].id.astype(str).to_numpy())
        pd.DataFrame({'participant_id':frames[key].id.astype(str),'filename':frames[key].filename,'split':name,'target':fy,'prediction':p.argmax(1),**{f'p_{label}':p[:,i] for i,label in enumerate(CLASS_NAMES)}}).to_csv(OUT/'fusion'/f'{name}_predictions.csv',index=False)
    (OUT/'comparison.json').write_text(json.dumps(report,indent=2));log('final_evaluation',results=report)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if not torch.cuda.is_available():raise RuntimeError('CUDA GPU required; refusing silent CPU fallback.')
    torch.set_num_threads(4);seed(SEED)
    protocol={'grade_configs':6,'grade_internal_folds':3,'grade_selection':'Equal-weight internal train-only CV macro-F1 and fixed validation macro-F1','fusion_backbones':['mobilenet_v3_small','efficientnet_b0','resnet18'],'fusion_internal_group_folds':3,'fusion_selection':'Train-only grouped CV selects backbone/head, fixed validation selects stopping point and frozen vs fine-tuned checkpoint','fine_tune_epochs_max':24,'test_evaluations':1,'originals_read_only':True,'no_fabricated_labels':True}
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2))
    log('start',gpu=torch.cuda.get_device_name(0),protocol=protocol)
    if '--resume' in sys.argv and (OUT/'grade/best_model.pt').exists():
        grade=torch.load(OUT/'grade/best_model.pt',map_location='cpu',weights_only=False)
        x,y,ids,_,splits=prepare_grade();data=(x.to_numpy(np.float32),y,ids,splits)
    else:grade,data=train_grade()
    model,fusion,frames,cache=train_fusion()
    if '--no-test' in sys.argv:log('training_complete_test_not_run')
    else:final_evaluation(grade,data,model,fusion,frames,cache)


if __name__=='__main__':main()
