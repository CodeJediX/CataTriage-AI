# CataTriage-AI

FastAPI research application hosted on Vercel, with private Supabase Postgres schemas for hospital, doctor and technician data. Original image bytes are stored in private Postgres tables. Uploads use authenticated 1 MB chunks to stay within Vercel request limits.

The same GPU-trained PyTorch checkpoints run on CPU in Vercel; model evidence and limitations are unchanged. No local computer or tunnel is required.

Set CATATRIAGE_DATABASE_URL and CATATRIAGE_SESSION_SECRET as server-only secrets; use the Supabase CA certificate bundled with the app. Apply the private schemas before starting. OPENROUTER_API_KEY is optional for scheduling explanations; Gemma remains primary and the configured free NVIDIA model is the fallback. Credentials, databases and raw datasets are excluded from Git.

Research and education only; use fictional patient records.
