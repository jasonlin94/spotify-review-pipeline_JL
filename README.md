# Spotify Reviews → Product Priority Pipeline

Multi-agent, code-coordinated pipeline that turns ~97.4 MB of real Spotify
reviews into an **auditable** product-priority recommendation. Every material
number traces to a saved calculation and source review; a reviewer can inspect
all conclusions **without rerunning any paid model call**.

> Status: **scaffold in progress.** This README maps each rubric category to
> evidence as the project fills in. Sections marked _TODO_ are not yet produced.

## Rubric → Evidence map (4 / 3 / 3)

| Rubric criterion | Evidence (links fill in as built) |
|---|---|
| **Deliverable quality (4)** — accessible setup/artifacts; clear architecture + shared schema + provenance; memo numbers linked to calculations; coherent recommendation + alternatives + limitations | `pipeline/`, `docs/architecture.md` _(TODO)_, `grading/`, `memo.md` _(TODO)_ |
| **Testing & evaluation (3)** — 50 human labels + per-field error analysis; independent verification + planted-error + injection tests; real 100-review cold/warm pilot + offline cost calculator + retry/spend/recovery controls | `evals/` _(TODO)_, `cost/` _(TODO)_ |
| **Working result (3)** — full ingestion + classification coverage; runnable staged program with bounded calls, saved handoffs, demonstrated resume; reproducible ranking + deployed dashboard | `pipeline/`, `web/` _(TODO)_, `grading/ranking.csv` _(TODO)_ |

## Scale decision

Classifying the **100,000-review** path (the assignment's allowed minimum) rather
than the full 660,609, given the deadline. Ingestion still profiles and accounts
for the full source file. The README states the exact classified count and marks
it honestly; coverage is scored proportionally.

## Architecture (six stages, code-coordinated)

```
raw CSV ─▶ 1 PREPARE ─▶ pending.jsonl ─▶ 2 CLASSIFY ─▶ enriched ─▶ 3 VERIFY
          (code)                         (Claude Haiku)            (Claude, independent)
                                                                      │
                            memo.md ◀─ 6 RECOMMEND ◀─ ranking.csv ◀─ 5 RANK ◀─ 4 GROUP
                            (Claude Sonnet)            (code, deterministic)   (code)
```
- **Code owns** record accounting, validation, dedup, ranking arithmetic, budgets, checkpoints.
- **Models read** messy language only, with bounded inputs and structured outputs.
- Full diagram + role input/output/stop-rules: `docs/architecture.md` _(TODO)_.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # then fill ANTHROPIC_API_KEY on your own machine
```

Dataset is **not committed** (97.4 MB). Download the course ZIP, unzip, and place
`spotify_reviews_18months.csv` at `data/raw/`. Source: BwandoWando "3.4 Million
Spotify Google Store Reviews" v2 (Kaggle, CC0). Checksum recorded in
`data/outputs/<run>/data_manifest.json`.

## Run

```bash
# Stage 1 — ingest + profile + dedup (no model, no key, free)
python -m pipeline.prepare --input data/raw/spotify_reviews_18months.csv --run-id full01

# Offline cost-calculator replay (no key, no paid calls)         # TODO
python -m cost.calculator --offline

# Regenerate ranking from saved outputs (no model)               # TODO
python -m pipeline.rank --from-saved data/outputs/full01

# Paid pilot / full classification — EXPLICIT, spends money       # TODO
python -m pipeline.run --input ... --paid
```

## Live dashboard

URL + access instructions: _TODO (Vercel; backend serves processed data from Postgres)._

## Results summary

_TODO: source/completed/quarantined counts, exact-text cache reuse, golden
agreement, verifier disagreements, measured 100-review cold/warm cost & time,
full-run projection._

## Limitations

Self-selected historical reviews (May 2022–Nov 2023). No account revenue, plan
tier, or confirmed churn — cancellation language is expressed intent, not observed
churn. First/last calendar months are partial. 50-case golden set is a small
diagnostic sample, not a population-accuracy estimate.
