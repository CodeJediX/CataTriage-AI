# Reproduction and verification

## Run the application

Use Python 3.12 on Windows or Linux. Create a virtual environment, install `requirements.txt`, then run `python -m uvicorn deployment.demo_app.main:app --host 127.0.0.1 --port 8000`. CPU inference is the default supported judging route; raw training data and API keys are not required. The initial package installation requires internet. After installation, the base local workflow and inference work without an external provider.

The public local fixture credentials in README are intentionally different from hosted credentials. Do not reuse them for a public deployment. The live website and the Android release use authorized hosted accounts.

`python tools/judge_smoke.py` starts the packaged application against a fresh temporary fictional database, disables external integrations, checks the three roles and guide, validates CSRF rejection, and loads both current model checkpoints.

Install `requirements-dev.txt` and run `python -m pytest tests -q`. The recorded workspace result is 110 passed. One raw-source image smoke test is skipped when its source image is absent. To force source-only verification, set `CATATRIAGE_TEST_NO_RAW_DATA=1`. Frozen fundus CSV split manifests are included without their image files.

## Training is a separate operation

The supplied checkpoints are sufficient for inference. Retraining needs data obtained from the cited providers. Set `CATATRIAGE_CLINICAL_DATA` to the Taizhou XLS file, `CATATRIAGE_CATSCREEN_DIR` to the extracted official sample root, and optionally `CATATRIAGE_CATSCREEN_CACHE` to a writable processed-image cache. The raw roots are read only; processed outputs belong in the project workspace.

GPU tuning used Python 3.11, PyTorch 2.11.0 with CUDA 12.8 and an NVIDIA RTX 2050 with 4 GB VRAM. `requirements-training.txt` includes the original demo/training requirements plus CatBoost 1.2.10; use the appropriate official CUDA PyTorch package index. Do not install the GPU training environment into the lightweight CPU judging environment.

The dated tuning utilities in `tools/` are experiment records. They assume the original datasets and split artifacts, version their outputs under `models/tuning_20261030`, seal selection hashes before final testing, and refuse to repeat final evaluation when `comparison.json` already exists. Do not tune repeatedly against a known test result. GPU CatBoost reductions and some accelerator operations may not reproduce bit-for-bit even with a fixed seed; the distributed checkpoints preserve the recorded model exactly.

## What the verification proves

Backend tests cover role boundaries, image validation, per-eye handling, account security, messaging, stale evidence, month boundaries, capacity, calendar conflicts, notifications, navigation and checkpoint compatibility. Isolated browser checks cover desktop/mobile overflow, keyboard controls, guide links and a bell that clears only after booking. Native Android instrumentation and lint were recorded for APK 1.1.0. Live smoke checks used non-persistent lab inputs and did not change clinical records or send messages.

These are engineering tests. They do not validate medical performance. The final v2 model comparison reused the same historical held-out sets once after validation selection. No claim of fresh external or future-time validation is made.
