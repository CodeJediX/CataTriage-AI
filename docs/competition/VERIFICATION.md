# Submission verification — 30 October 2026

The source-only regression run in the prepared checkout passed **109 tests**, with **one optional original-image test skipped** because raw datasets are excluded. The earlier full workspace run recorded 110 passed. These counts describe local runs, not GitHub Actions or clinical validation.

`tools/judge_smoke.py` passed against fresh temporary fictional records, with external services and CUDA disabled. It checked all three login roles, role pages, navigation guide, CSRF rejection and loading both v2 checkpoints. No live record was changed. The run used the existing compatible Python environment; a fresh dependency installation was not performed for this packaging check.

The technical report is eight pages, the summary exactly two pages, and current model evidence three pages. All Word copies were exported using Microsoft Word and their rendered pages inspected. The standard document renderer was unavailable because LibreOffice was not installed. Historical PDFs are preserved, with editable archival Word transcriptions rather than an assertion of exact original page layout.

The package builder checks tracked files, README links, PDF/Word counterparts, excluded paths, common credential patterns, ZIP CRC and the SHA-256 of every archived file. This review is not a formal security certification. The manifest records the exact Git commit. Raw datasets, operational patient records, uploads, secrets and Android signing material are excluded.

The provided Android APK is the existing signed 1.1.0 doctor release; it was not rebuilt in this packaging step. Its earlier lint and instrumentation results are release history, not newly repeated tests. Model metrics and checkpoints were not retrained or changed during document preparation.
