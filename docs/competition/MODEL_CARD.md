# Current research model card

## Grading v2

Target: maximum available bilateral NO, NC, cortical and PSC grade, grouped into 0, 1, 2 or 3+. Inputs: 44 source clinical fields and 97 numerical/derived representations. A GPU CatBoost tree model contributes 75% of the probabilities; the existing neural classifier contributes 25%. The exported tree arrays run with NumPy, without a CatBoost runtime dependency.

Accuracy train/validation/test: **70.79 / 54.36 / 56.04%**. Test macro F1 **56.67%**, balanced accuracy **57.38%**, weighted kappa **0.698**, grade MAE **0.510**. Seven more exact test predictions than the previous model: **167/298 versus 160/298**. Approximate participant bootstrap accuracy interval **50.7–61.7%**. Missing web-form fields use training medians, and incomplete-input warnings are shown; full-record scores do not establish incomplete-form performance.

## Image context fusion v2

Target: normal, cataract or other ocular condition, not cataract severity or surgery urgency. Inputs: a 224-pixel RGB slit-lamp image plus nine encoded laterality/acquisition values. Probability blend: existing MobileNetV3-Small context CNN 75%, ResNet-18 context CNN 25%. The latter uses pretrained image features and a trained context/classification head. Fine-tuning that overfit was rejected.

Accuracy train/validation/test: **72.14 / 65.00 / 55.00%**. Test balanced accuracy **60.19%**, macro F1 **47.93%**. One additional correct test image: **22/40 versus 21/40**. Recall: normal **2/8**, cataract **15/27**, other **5/5**. Approximate participant-cluster bootstrap accuracy interval **37.5–71.4%**. These class counts are too small for a clinical claim.

Unknown eye side averages left/right context hypotheses; it does not infer anatomical laterality. Unknown-side performance has not been independently validated. Previous training accuracy used random augmentation and is not directly comparable to the new deterministic evaluation.

## Scope and non uses

The models support retrospective research and demonstration. They do not establish diagnosis, clinical severity, surgical suitability, safe waiting time or queue priority. A doctor enters the workflow tier and approves an elective month. The admin chooses a date after capacity checks. The AI scheduling endpoint only ranks supplied operational candidates.

The separate EfficientNet-B0 V3 fundus baseline reports 72.53% accuracy on 91 image-level test examples. Its four-class task is different; its score cannot be compared as if it were the same cataract grading task. Synthetic simulation model scores are generator/pipeline checks and are excluded from the real-data performance claims.

Exact checkpoints, original baselines, metrics, validation-search records and selection hashes are in the corresponding model directories. No additional tuning followed the final v2 test results. More verified labels and independent contemporary cohorts are needed before stronger claims.
