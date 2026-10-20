# Cost & Runtime Report — 100-review pilot

_Offline replay. API tier shown: **paid**. Recompute anytime with_ `python -m cost.calculator offline`.

## Measured on cost_100.csv (facts)

- Input tokens: **3714**, output tokens: **1473**
- Completed: **100**, failed: **0**
- Cold wall-clock: **10.76 s**; warm wall-clock: **0.01 s**
- Warm run new enrichment calls: **0** (cache reuse)
- API cost @ paid: **$0.004707**  (free tier actual = $0; paid shown for projection)
- Cost per 1,000 input rows: $0.047069; per completed record: $4.707e-05

### By stage

| stage | model | input tok | output tok | cost |
|---|---|---|---|---|
| enrich | gemini-3.5-flash-lite | 2827 | 1229 | $0.00379407 |
| verify | gemini-3.5-flash-lite | 366 | 192 | $0.00055566 |
| group | gemini-3.5-flash-lite | 521 | 52 | $0.00035721 |

## Full-run projection (estimate)

Scaling the enrichment stage by distinct texts; fixed overhead (verify/group/memo) added once. Budget $5.0, fallback fraction 0.05.

| scenario | distinct/nonempty | projected API cost | over budget? |
|---|---|---|---|
| exact-text reuse, base | 484,189 | $19.2899 | True |
| exact-text reuse, conservative (+15% retries) | 484,189 | $22.1833 | True |
| NO reuse, base | 660,609 | $26.3181 | True |
| NO reuse, conservative | 660,609 | $30.2657 | True |

## Controls

- Editable budget: $5.0
- Output-token cap: 1024
- Max workers: 1
- Max fallback fraction: 0.05

## Local compute (not an API charge)

The orchestrator runs on the student's machine (Windows, Intel Arc iGPU). No GPU inference is used locally for the Gemini path; local cost is wall-clock time + electricity only and is not billed by the provider.

## Rates used (editable; see rates.csv)

| model | tier | in/1M | cached/1M | out/1M | source | checked |
|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | paid | 0.49 | 0.12 | 1.96 | https://ai.google.dev/gemini-api/docs/pricing | 2026-10-19 |
| gemini-3.5-flash-lite | free | 0.0 | 0.0 | 0.0 | https://ai.google.dev/gemini-api/docs/rate-limits | 2026-10-19 |