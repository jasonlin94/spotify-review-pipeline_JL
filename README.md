# Spotify Reviews → Product-Priority Pipeline

A multi-agent, code-coordinated pipeline that turns **97.4 MB of real Spotify
reviews** (660,622 rows) into an **auditable** product-priority recommendation.
Every material number traces to a saved deterministic calculation and to source
reviews, and a reviewer can inspect all conclusions **without rerunning any paid
model call**.

- **Stack:** Python pipeline · Google Gemini `gemini-3.5-flash-lite` (cheapest
  available flash-lite tier) for the bounded language tasks · Next.js dashboard +
  API backend + Postgres.
- **Distinct model roles** (enrich / verify / group / memo) with separate
  instructions, inputs, outputs and saved evidence, coordinated by code.

## Rubric → evidence map (4 / 3 / 3)

| Criterion | Evidence |
|---|---|
| **Deliverable quality (4)** — accessible setup/artifacts | this README, `pipeline/`, `requirements.txt`, `.env.example` |
| …clear architecture, shared schema, provenance | [Architecture](#architecture) · `pipeline/labels.py`, `pipeline/schema.py`, `pipeline/hashing.py` |
| …memo numbers linked to calculations + source | `memo.md`, `grading/claims.csv`, `grading/ranking.csv` |
| …coherent recommendation + alternatives + limitations | `memo.md` |
| **Testing & evaluation (3)** — 50 human labels + per-field error analysis | `evals/golden_50_labeled.csv`, `evals/run_golden.py` → `evals/golden_results.json` |
| …independent verification + planted-error + injection | `pipeline/verify.py` → `verify_report.json`; `evals/planted_error.py` (3/3 caught); `evals/injection_test.py` (4/4 resisted) |
| …real 100-review cold/warm pilot + offline calculator + retry/spend/recovery | `cost/` (cold 10.8s / warm 0s) · resume demo · `pipeline/recover.py` |
| **Working result (3)** — full ingestion + classification coverage | `grading/ingestion.json`, `grading/records.jsonl` |
| …runnable staged program, bounded calls, saved handoffs, demonstrated resume | `pipeline/` · `grading/checkpoint_before.json` / `checkpoint_after.json` |
| …reproducible ranking + deployed dashboard | `pipeline/rank.py` (no-model rerank) · `web/` (live URL below) |

## Architecture

Six code-coordinated stages. **Code owns** record accounting, validation, dedup,
ranking arithmetic, budgets and checkpoints; the **model reads messy language
only**, with bounded inputs (≤50 reviews/request) and structured outputs.

```
raw CSV ─▶ 1 PREPARE ─▶ pending.jsonl ─▶ 2 CLASSIFY ─▶ enriched.jsonl ─▶ 3 VERIFY
          (code only)                    (Gemini, ≤50/req)              (Gemini, independent sample)
                                                                           │
   memo.md ◀─ 6 RECOMMEND ◀─ ranking.csv ◀─ 5 RANK ◀─ membership.csv ◀─ 4 GROUP
   (Gemini, grounded)        (code, deterministic)   (code; model names issues)

   grading/ export ─▶ check_submission.py (zero-API self-check)
   Postgres ◀─ db/seed.mjs ◀─ web/data/snapshot.json ◀─ db/make_snapshot.py
   Next.js dashboard  ─fetch▶  /api/* (backend)  ─query▶  Postgres
```

Each stage has a defined input, output, owner, failure behavior and stop
condition. Invalid model output is retried once then quarantined; rate-limit /
network errors are retried with bounded backoff and otherwise left **pending**
for a resume (never silently dropped).

## Scale decision

Ingestion profiles and accounts for the **entire** 660,622-row file. Enrichment
targets the full corpus (484,189 distinct nonempty texts via exact-text reuse);
the assignment's **100,000-review minimum** is the guaranteed floor and the run
is resumable toward full coverage. The README reports the exact classified count
(coverage is scored proportionally). Empty texts (13) are quarantined
`empty_review_text`; other failures remain visible and reduce the completed
fraction.

## Setup

```bash
python -m venv .venv && . .venv/Scripts/activate       # Windows
pip install -r requirements.txt
cp .env.example .env     # then put GEMINI_API_KEY=... in .env (never commit it)
```

Dataset is **not committed** (97.4 MB). Download the course ZIP, unzip, and place
`spotify_reviews_18months.csv` under `data/dataset/`. Source: BwandoWando
"3.4 Million Spotify Google Store Reviews" v2 (Kaggle, CC0). File SHA-256
`1fc85de68a304dd8978b537cfa58793d5f41cbaf417fa32cb53899f83a2fcef6`
(verified; matches `manifest.json`).

## Run

```bash
# Stage 1 — ingest + profile + dedup (no model, no key, free)
python -m pipeline.prepare  --input data/dataset/spotify_reviews_18months.csv --run-id full01

# Stage 2 — classify (paid; resumable; ≤50/request).  Re-running resumes with 0 re-pay.
python -m pipeline.classify --input data/dataset/spotify_reviews_18months.csv --run-dir data/outputs/full01

# Optional recovery pass for garbage/emoji reviews that failed formatting
python -m pipeline.recover  --input data/dataset/spotify_reviews_18months.csv --run-dir data/outputs/full01

# Stages 3-6
python -m pipeline.verify  --run-dir data/outputs/full01 --input data/dataset/spotify_reviews_18months.csv --sample 400
python -m pipeline.group   --run-dir data/outputs/full01
python -m pipeline.rank    --run-dir data/outputs/full01          # deterministic, no model
python -m pipeline.export_grading --run-dir data/outputs/full01 \
    --analysis-csv data/dataset/spotify_reviews_18months.csv \
    --full-csv data/dataset/spotify_reviews_18months.csv \
    --checker data/dataset/check_submission.py --out grading
python -m pipeline.memo    --grading grading --run-dir data/outputs/full01 --out memo.md

# Offline cost replay (no key, no paid calls) and golden eval (after labeling)
python -m cost.calculator offline
python -m evals.run_golden --reviewer "Your Name"

# Zero-API self-check (the grader's own tool)
python data/dataset/check_submission.py profile   --full data/dataset/spotify_reviews_18months.csv --out grading/ingestion.json
python data/dataset/check_submission.py reference --full data/dataset/spotify_reviews_18months.csv --analysis data/dataset/spotify_reviews_18months.csv --out local-reference.json
python data/dataset/check_submission.py check     --reference local-reference.json --submission grading --out self-check.json
```

## Live dashboard

**URL: https://spotify-review-pipeline-jl.vercel.app/** (public, no login) ·
deployment steps in [`web/DEPLOY.md`](web/DEPLOY.md).

Deployed on Vercel. The backend (`/api/*`) reads the processed data from a
**Neon Postgres** database (seeded via `db/seed.mjs` from `db/make_snapshot.py`
output) and serves overall metrics, the issue ranking, and the AI-generated
recommendation with supporting numbers and click-through issue → source-review
evidence. The header badge shows `source: postgres` when served from the
database (it falls back to the committed JSON snapshot if the DB is
unreachable). No paid model calls are needed to inspect anything.

## Results summary

_Ingestion (verified, exact match to `manifest.json`):_

| metric | value |
|---|---|
| rows total | 660,622 |
| nonempty | 660,609 · empty (quarantined) 13 |
| distinct nonempty texts | 484,189 (exact-text reuse saves 176,420 first-pass calls) |
| missing app_version | 159,701 · duplicate review_ids 0 |

_Classification (final, 100k-path within the $5 budget):_ **107,950** reviews
classified (completed), **63** quarantined (13 empty-text + 50 garbage/emoji
strings that fail structured formatting). Official-checker **coverage point
candidate 0.3307** (= 0.2 full-file profile match + 0.2×accounted/660,622 +
0.6×valid/660,609); all records / membership / ranking / claims pass with no
schema, source-hash, quote, or ranking mismatches. The run was credit-capped at
$5 (prepaid); the pipeline is resumable toward full coverage.

_Baseline ranking (deterministic):_ **#1 playback** (12,902 complaints, mean
severity 3.369, priority 43,467), #2 usability (13,497 complaints, mean 2.514,
priority 33,931), then catalog, access, billing, downloads, other, support.

_Independent verification (400-review declared sample, Gemini):_
topic agreement **0.603**, intent **0.950**, severity exact **0.850**, severity
MAE **0.156**; see `verify_report.json` and its concrete disagreements.

_Decision memo:_ recommends **Playback** (crashing/shuffle stability), citing
claim IDs C1–C3 and representative review IDs — every citation code-validated.

_System tests:_ prompt-injection **4/4 ignored**; planted-error **3/3 caught**.

_Cost (measured on `cost_100.csv`):_ 3,714 input / 1,473 output tokens; cold
**10.8 s**, warm **~0 s with 0 new enrichment calls**; API cost ≈ **$0.001** at
the paid flash-lite rate (**$0** actual on the free tier used to measure).
Full-run projection with exact-text reuse: base ≈ **$3.94**, conservative ≈
**$4.53** (within the $5 budget); without reuse ≈ $5.37 / $6.18 (flagged
over-budget). See `cost/report.md`; `offline` replay recomputes it with no key.

_Determinism:_ the official `check_submission.py` validated records /
membership / ranking / claims on the 100- and 500-review checkpoints
(`working_coverage_point_candidate = 1.0` on those scopes).

## One review, traced end to end

`review_id 45c561b9-cc47-4d80-95d3-f0d20bc84af3` →
Stage 2 enrich → `topic=usability, intent=cancellation, severity=3,
evidence_quote="The update made the app useless …. Uninstall …"` →
Stage 4 group → issue `usability` → Stage 5 rank → contributes to the
`usability` issue's `priority_score` (ranked #2). The memo's top recommendation
is `playback` (#1), citing its own representative reviews. An ambiguous/handled
case: garbage text like
`"22i2I 122"` fails structured formatting → quarantined `invalid_model_output`
(reason + attempt count preserved) rather than guessed.

## Limitations

Self-selected historical reviews (May 2022 – Nov 2023); first/last calendar
months are partial. No account revenue, plan tier, or confirmed churn —
cancellation language is **expressed intent, not observed churn**; no revenue-at-
risk or causal retention claims are made. The 50-case golden set is a small
diagnostic sample, not a population-accuracy estimate.

## Security

Real keys live only in a local `.env` (git-ignored; `git check-ignore .env`
prints `.env`). Only a blank `.env.example` and the `.gitignore` rules are
committed. Offline cost replay and all saved-output checks work without
credentials.
