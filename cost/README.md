# Cost & Runtime Calculator (100-review pilot)

Measures the real pipeline on the fixed `cost_100.csv`, then lets the grader
recompute every number **offline, with no API key and no model calls**.

## Offline replay (default — no key, no paid calls)

```bash
python -m cost.calculator                      # offline, paid-tier projection, $5 budget
python -m cost.calculator offline --tier free  # show the $0 free-tier actual
python -m cost.calculator offline --budget 5 --fallback-fraction 0.05
```

Reads `usage.csv` (measured tokens) + `rates.csv` (editable, dated prices) and
writes `report.md`. Opening/importing the calculator makes **no** API calls.

Arithmetic: `item_cost = billed_units × (price_per_1m / 1_000_000)`; cached input
is billed at the cached rate; `total = Σ item_cost`. With usage fixed, doubling a
rate doubles that API subtotal (verified) and leaves measured time unchanged.
Changing the projected record count never changes the measured-100 numbers.

## Explicit paid pilot (spends money — separate command)

```bash
python -m cost.calculator run-pilot            # runs cold then warm on cost_100.csv
```

Runs the full pipeline (enrich → verify sample → group → rank → memo) cold with an
empty result cache, then warm (reuse) demonstrating **zero new enrichment calls**,
and saves the evidence below.

## Files

| File | Contents |
|---|---|
| `calculator.py` | the calculator (offline default; `run-pilot` is the only paid path) |
| `rates.csv` | editable per-model, per-tier token prices with dated source links |
| `usage.csv` | measured per-stage token totals from the pilot |
| `pilot_records.jsonl` | one record per pilot ID (contract row hash + common labels) |
| `pilot_calls.jsonl` | every cold/warm model attempt with role/model/usage/timing |
| `pilot_meta.json` | cold/warm wall-clock, warm new-enrichment-call count, counts |
| `report.md` | measured-100 dashboard + full-run projection + controls |

## Headline numbers (measured + projected)

- Measured 100: ~3,714 input / ~1,473 output tokens; cold ≈ 10.8 s, warm ≈ 0 s
  (0 new enrichment calls); API cost ≈ **$0.001** at the paid flash-lite rate,
  **$0** actual on the free tier used for measurement.
- Full-run projection **with exact-text reuse** (484,189 distinct): base ≈
  **$3.94**, conservative ≈ **$4.53** — within the $5 budget.
- **Without** reuse (660,609): ≈ $5.37 / $6.18 — exceeds $5 (flagged), which is
  why exact-text reuse is enabled.

Local compute (the orchestrator on the student's machine) is not an API charge
and is listed separately; the Gemini path runs no local GPU inference.
