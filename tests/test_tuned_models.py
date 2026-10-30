import json
from pathlib import Path
import numpy as np
import torch
from deployment.demo_app import real_models
from test_demo import png_bytes


def test_promoted_models_are_versioned_and_improve_both_validation_and_test():
    root=Path(__file__).resolve().parents[1]
    for folder in ('cataract_grade_multidata_real','clinical_fusion_catscreen_real'):
        m=json.loads((root/'models'/folder/'metrics.json').read_text(encoding='utf-8'))
        assert m['model_version']=='v2'
        for split in ('validation','test'):
            assert m['metrics'][split]['accuracy']>=m['baseline_metrics'][split]['accuracy']
            assert m['metrics'][split]['macro_f1']>=m['baseline_metrics'][split]['macro_f1']
        assert m['selection_lock']['test_predictions_used_for_selection'] is False


def test_new_checkpoints_run_without_catboost_or_weight_downloads():
    provider=real_models.RealModelProvider();provider._device=torch.device('cpu')
    result=provider.analyze_tabular({'age':65,'gender':1,'UCVA Right eye':.7})
    assert result['model_id']=='cataract_grade_multidata_real_v2'
    assert result['input_completeness_warning'] and result['uncertainty_warning']
    assert abs(sum(result['probabilities'].values())-1)<1e-5
    known=provider.analyze_fusion(png_bytes(),'slit_lamp',{'eye_side':'Left'})
    unknown=provider.analyze_fusion(png_bytes(),'slit_lamp',{'eye_side':'Not recorded'})
    assert known['model_id']==unknown['model_id']=='clinical_fusion_catscreen_real_v2'
    assert unknown['laterality_unknown']
    for output in (known,unknown):
        assert output['clinical_priority'] is None and output['requires_clinician_review']
        assert abs(sum(output['probabilities'].values())-1)<1e-5
