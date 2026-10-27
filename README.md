# CataTriage-AI educational demo

FastAPI app with real-data trained research models, four auditable processing stages, and separate doctor, admin and technician portals.

Run `uvicorn deployment.demo_app.main:app --host 0.0.0.0 --port 10000`. Install requirements.txt first. Set CATATRIAGE_HOSTED=true and private CATATRIAGE_DOCTOR_PASSWORD, CATATRIAGE_ADMIN_PASSWORD, CATATRIAGE_TECHNICIAN_PASSWORD (16+ characters) through host secrets.

Free Render hosting is temporary: database and uploads reset on restart, redeploy or idle sleep. Real local patient records, source datasets and API credentials are excluded from this repository. Model accuracy and limitations are available in the app. Research use only.
