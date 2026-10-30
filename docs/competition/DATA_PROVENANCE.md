# Data provenance and temporality

## What was actually used

| Artifact | Actual unit and split | Temporal facts | Important gaps |
| --- | --- | --- | --- |
| Taizhou grading | 1,986 participants; 1,390 train, 298 validation, 298 test; one row per participant | The source study was conducted July–September 2012. Dryad published the data on 7 August 2016. Local v2 tuning was completed on 30 October 2026 in Asia/Colombo. | Rural Chinese adults aged at least 45; not a contemporary hospital cohort. Derived maximum bilateral grade, no externally adjudicated endpoint. |
| CatScreen fusion | 200 clean public-snapshot images; 140 train, 20 validation, 40 test; 129/19/37 participants | Public snapshot downloaded 26 October 2026. The cited paper is TMLR 2026. Acquisition dates were not verified from the local snapshot and must not be inferred from publication/download dates. | Only a small sample of the full release; no verified full clinical history, no future-time cohort, and weak normal recall. |
| Fundus V3 baseline | 601 images; 420/90/91 image-level split | Original acquisition dates were not established; model artifacts predate the current implementation, with the handover recorded through 24 October 2026. | Reliable patient IDs unavailable; no participant-level independence claim. Different modality and target from slit-lamp grading. |
| Workflow fixtures | Sixteen fictional built-in cases and dynamically generated demo dates | Current application dates and waiting times are simulated operational data, not a longitudinal patient outcome dataset. | Cannot validate clinical scheduling, access delays or patient outcomes. |

The grading cohort and CatScreen images are **not linked**. The application does not pretend they form paired multimodal patients. “Multi-data” refers to diverse structured fields in one clinical cohort; “fusion” currently refers to image plus acquisition context. There is no chronological train/test split or verified prospective validation for either model.

## Rights and exclusions

Taizhou source: Tang et al., Dryad DOI https://doi.org/10.5061/dryad.gt410, CC0. The associated study is https://doi.org/10.1371/journal.pone.0135870. Official source metadata confirms the 2012 collection period and 2016 dataset publication.

CatScreen source: https://www.iab-rubric.org/resources/healthcare-datasets/catscreen. Cite Khurshid et al., *CatScreen A Large MultiModal Benchmark Dataset for Cataract Screening*, TMLR 2026. The public clean snapshot was obtained through the provider's published sample release; the full release is research/education-only and requires the provider's institutional license process. It was not obtained or trained in full. Raw images are not redistributed in the submission.

The broader original inventory contained unverified slit-lamp grading material, temporal sequences and uncertain-provenance images. Those were not relabelled by filename or used as new severity/urgency ground truth. AUTO_PILOT labels and excluded duplicate collections were not used to claim real-data performance.

## Evaluation safeguards

Participant IDs are disjoint across Taizhou splits and the official CatScreen splits. Exact cached-image hashes were checked across CatScreen splits. Preprocessing fits only training data. Direct grade fields, cataract diagnoses, cataract history/surgery and lens status are excluded from grading inputs. Image context excludes the diagnosis and grade columns. These checks do not prove absence of all near-duplicates or source/device shortcuts.

The original historical tests were reused once after the v2 candidates and blend weights were sealed. They are not previously unseen external cohorts. Reported improvements are small; intervals overlap the prior scores. No calibration, clinical safety, prospective, subgroup or external validation is claimed.

Evaluation CSVs contain public-source research identifiers, filenames, target classes and model predictions. They contain no operational patient records or raw image pixels. Original acquisition metadata and rights must still be obtained from the dataset providers.
