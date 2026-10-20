# Deploying the dashboard (Vercel + Postgres)

The dashboard is a Next.js app. Its API routes (the **backend**) read the
analysis from **Postgres** in production and serve it to the browser
(**frontend**). Locally, with no `DATABASE_URL`, the same APIs fall back to the
committed `web/data/snapshot.json` so the UI runs without a database.

## 1. Build the data snapshot (no API calls)

```bash
# from repo root, after the pipeline + grading export have run
python -m db.make_snapshot --run-dir data/outputs/full01 \
    --grading grading --out web/data/snapshot.json
```

## 2. Provision a Postgres database

Either **Vercel Postgres** (Storage tab → Create → Postgres) or **Neon**
(neon.tech, free tier). Copy its connection string (`postgres://...`).

## 3. Seed the database (one-time, no API calls)

```bash
DATABASE_URL='postgres://USER:PASS@HOST/DB?sslmode=require' node db/seed.mjs
```

This applies `db/schema.sql` and loads the snapshot into Postgres.

## 4. Deploy to Vercel

- Import the GitHub repo in Vercel; set **Root Directory = `web`**.
- Add environment variable **`DATABASE_URL`** (same value as step 3).
- Deploy. Vercel builds `web/` and serves the dashboard + API routes.
- With `DATABASE_URL` set, the backend reads Postgres (confirm the header badge
  shows **source: postgres**). Without it, it shows **source: snapshot**.

## Local dev

```bash
cd web && npm install && npm run dev      # http://localhost:3000  (uses snapshot)
# or against Postgres:
DATABASE_URL='postgres://...' npm run dev  # backend reads the database
```

## What the grader sees

- Overall metrics (ingested / classified / quarantined / distinct / reuse).
- Issue ranking (priority = severity_sum = count × mean severity), matching
  `grading/ranking.csv` exactly.
- AI-generated recommendation with supporting claim IDs + representative review
  IDs (from the grounded memo).
- Click any issue → its source-review evidence (severity, intent, exact quote):
  traceable issue → review evidence. No paid model calls are needed to inspect.
