# Configuration and deployment

## No configuration for the local demo

Without cloud settings the application creates three local SQLite files with fictional fixtures. No API keys are bundled. Set `CATATRIAGE_DATA_DIR` to a private writable directory if you want to choose where local records are stored.

## Cloud mode

Use server-only `CATATRIAGE_DATABASE_URL`, `CATATRIAGE_SESSION_SECRET`, `CATATRIAGE_HOSTED=true` and private `CATATRIAGE_DOCTOR_PASSWORD`, `CATATRIAGE_ADMIN_PASSWORD` and `CATATRIAGE_TECHNICIAN_PASSWORD` values of at least 16 characters. Do not put these in frontend code or Git. The supplied Supabase CA certificate is a public trust certificate, not a private key.

Apply `deployment/cloud/schema.sql`, then `images.sql`, `doctor_communications.sql`, `account_management.sql`, `firebase_mail.sql` and `profile_month_planning.sql` to a separately provisioned private Postgres project. Review role creation and set the app-role password privately. The SQL is administrative setup, not a public browser API. Use TLS verification and keep anonymous/authenticated access revoked from private application tables. Production configuration and source records are not included.

The Vercel entry point is `app.py`; `vercel.json` selects the FastAPI runtime, region and required model/artifact files. Hosted inference is CPU inference using the same saved GPU-trained checkpoints. No new cloud project, billing change or production credentials are needed to inspect the ZIP locally. Free hosting and AI endpoint availability can vary and should not be treated as a service-level guarantee.

## Optional services

OpenRouter scheduling: set `AI_ENABLE`, `AI_PROVIDER=openrouter`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` and `OPENROUTER_FALLBACK_MODELS` privately. Candidate validation remains in force and outages use local planning rules. The navigation guide does not call this API.

Firebase doctor setup and automatic WhatsApp need separate provider configuration. See `docs/DOCTOR_COMMUNICATIONS_SETUP.md`. Do not distribute an Android signing keystore or provider credentials. Keep production account access separate from local fixture credentials.
