"""Promote sealed candidates only after a non-regression check; retain local v1 backups."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import torch
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'models/tuning_20261030'


def plot_scores(folder,old,new,title):
    fig,axes=plt.subplots(1,2,figsize=(11,4.2))
    splits=['train','validation','test'];values=[new[k]['accuracy'] for k in splits]
    bars=axes[0].bar(splits,values,color=['#387b85','#b78645','#087f78'],width=.55)
    for bar,value in zip(bars,values):axes[0].text(bar.get_x()+bar.get_width()/2,value+.025,f'{value:.1%}',ha='center',fontweight='bold',fontsize=10)
    axes[0].set(title='Selected model: standard evaluation',ylabel='Accuracy',ylim=(0,1))
    labels=['Previous','Tuned'];values=[old['metrics']['test']['accuracy'],new['test']['accuracy']]
    bars=axes[1].bar(labels,values,color=['#a6b4bb','#087f78'],width=.5)
    for bar,value in zip(bars,values):axes[1].text(bar.get_x()+bar.get_width()/2,value+.025,f'{value:.1%}',ha='center',fontweight='bold')
    axes[1].set(title='Same historical test set',ylabel='Accuracy',ylim=(0,1))
    for ax in axes:ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True);ax.spines[['top','right']].set_visible(False)
    fig.suptitle(title,fontsize=13,fontweight='bold');fig.tight_layout();fig.savefig(folder/'training_curves.png',dpi=170);plt.close(fig)


def confusion(folder,matrix,labels,title):
    cm=np.asarray(matrix);fig,ax=plt.subplots(figsize=(6.5,5.3));im=ax.imshow(cm,cmap='Blues')
    for i in range(len(labels)):
        for j in range(len(labels)):ax.text(j,i,str(cm[i,j]),ha='center',va='center',fontweight='bold',color='white' if cm[i,j]>cm.max()/2 else '#163d43')
    ax.set(xticks=range(len(labels)),yticks=range(len(labels)),xticklabels=labels,yticklabels=labels,xlabel='Predicted',ylabel='Recorded label',title=title);fig.colorbar(im,ax=ax,fraction=.046);fig.tight_layout();fig.savefig(folder/'test_confusion_matrix.png',dpi=170);plt.close(fig)


def main():
    comparison=json.loads((OUT/'comparison.json').read_text());lock=json.loads((OUT/'selection_lock.json').read_text())
    for key,folder_name in (('grade','cataract_grade_multidata_real'),('fusion','clinical_fusion_catscreen_real')):
        new=comparison[key];old=json.loads((OUT/f'baseline_{key}.json').read_text());target=ROOT/'models'/folder_name
        for split in ('validation','test'):
            assert new[split]['macro_f1']>=old['metrics'][split]['macro_f1'],f'{key} {split} macro-F1 regressed'
            assert new[split]['accuracy']>=old['metrics'][split]['accuracy'],f'{key} {split} accuracy regressed'
        source=OUT/lock['files'][key]['path'];assert hashlib.sha256(source.read_bytes()).hexdigest()==lock['files'][key]['sha256']
        backup=ROOT/'models/archive/real_v1_20261030'/folder_name
        if not backup.exists():shutil.copytree(target,backup)
        shutil.copy2(source,target/'best_model.pt')
        saved=torch.load(source,map_location='cpu',weights_only=False)
        updated={**old,'created_at_utc':comparison['created_at_utc'],'model_version':'v2','model_id':saved['model_id'],'metrics':{k:new[k] for k in ('train','validation','test')},'test_confusion_matrix':new['test_confusion_matrix'],'test_accuracy_bootstrap_95ci':new['test_accuracy_bootstrap_95ci'],'baseline_metrics':old['metrics'],'test_accuracy_change_points':new['test_accuracy_change_points'],'test_reuse_note':comparison['test_policy'],'inference_evaluation':comparison['inference_for_final_metrics'],'selection_lock':lock,'tuning_summary':'Training/validation-selected model blend. Historical test used once for final non-regression check; no further tuning after test results.','uncertainty_note':'Small measured improvement; intervals are wide and no statistical superiority or clinical validation is established.'}
        if key=='grade':
            updated['architecture']='GPU CatBoost numerical ensemble (75%) + existing grade neural network (25%).'
            updated['selected_hyperparameters']={'tree_weight':saved['tree_weight'],'tree_config':saved['tree']['selected']}
            updated['input_features']=len(saved['features']);updated['engineered_features']=len(saved['features'])*2+9
            updated['epochs']='896 boosted trees; existing neural checkpoint retained'
            labels=saved['labels'];history=json.loads((OUT/'grade/leaderboard.json').read_text())
            fig,ax=plt.subplots(figsize=(8.5,4));ax.plot(range(1,len(history)+1),[r['validation']['accuracy'] for r in history],marker='o',label='Validation accuracy');ax.plot(range(1,len(history)+1),[r['cv_macro_f1'] for r in history],marker='o',label='Train-only CV macro-F1');ax.set(xlabel='Fixed CatBoost candidate',ylabel='Score',ylim=(0,1),title='GPU tuning: six configurations, three internal folds');ax.legend();ax.grid(alpha=.2);fig.tight_layout();fig.savefig(target/'tuning_history.png',dpi=170);plt.close(fig)
            updated['limitations'] += ['Only a small validation improvement was found; more training does not manufacture missing clinical information.','Partially entered web forms use training-set medians. Full-record benchmark accuracy does not establish performance on incomplete records.']
        else:
            updated['architecture']='Probability blend: existing MobileNetV3-Small context CNN (75%) + pretrained ResNet-18 context CNN (25%).'
            updated['selected_hyperparameters']={'secondary_weight':saved['secondary_weight'],'secondary_config':saved['secondary']['selected']}
            updated['best_epoch']='Validation-selected blend; overfitted fine-tuning rejected';updated['epochs_run']=10
            for split in ('train','validation','test'):updated['metrics'][split]['per_class_recall']=dict(zip(saved['classes'],new[split]['per_class_recall']))
            labels=saved['classes'];history=json.loads((OUT/'fusion/history.json').read_text())['fine_tuning']
            fig,ax=plt.subplots(figsize=(8.5,4));ax.plot([r['epoch'] for r in history],[r['train_accuracy'] for r in history],label='Component training accuracy');ax.plot([r['epoch'] for r in history],[r['validation_accuracy'] for r in history],label='Component validation accuracy');ax.set(xlabel='Fine-tuning epoch',ylabel='Accuracy',ylim=(0,1.04),title='Rejected fine-tuning: high training scores did not generalise');ax.legend();ax.grid(alpha=.2);fig.tight_layout();fig.savefig(target/'tuning_history.png',dpi=170);plt.close(fig)
            updated['limitations'] += ['Normal-class recall remains only 25% on eight normal test images.','The original training metric used random augmentation; the new training score uses deterministic evaluation, so those training scores are not directly comparable.','A 99% training-accuracy candidate was rejected due to validation overfitting.']
        (target/'metrics.json').write_text(json.dumps(updated,indent=2,ensure_ascii=False),encoding='utf-8')
        plot_scores(target,old,new,'Multi-data grading' if key=='grade' else 'Slit-lamp image-context fusion')
        confusion(target,new['test_confusion_matrix'],labels,'Historical held-out test: tuned research model')
        pd.concat([pd.read_csv(OUT/key/f'{split}_predictions.csv') for split in ('train','validation','test')]).to_csv(target/'predictions_and_splits.csv',index=False)
        shutil.copy2(OUT/'protocol.json',target/'tuning_protocol.json')
        print(json.dumps({'promoted':folder_name,'test_accuracy':new['test']['accuracy'],'macro_f1':new['test']['macro_f1'],'checkpoint_sha256':hashlib.sha256((target/'best_model.pt').read_bytes()).hexdigest()}))


if __name__=='__main__':main()
