# Contract alignment checklist (do this when the dataset ZIP arrives)

The code currently encodes the schema/taxonomy from the assignment PDF. Before
the paid run, reconcile against the authoritative files inside the ZIP and fix
any mismatch here first.

- [ ] Read `GRADING_CONTRACT.md` → confirm exact `records.jsonl` field names + order
      (update `pipeline/schema.py: REQUIRED_KEYS`).
- [ ] Confirm the **source hashing rule** (newline normalization? which field?)
      → `pipeline/schema.py: source_sha256`.
- [ ] Confirm topic/intent/severity boundary wording + examples
      → `pipeline/labels.py` (label SET is fixed; only wording/examples may change).
- [ ] Read `COST_CALCULATOR.md` → exact `cost/` file checklist
      (pilot_records.jsonl, pilot_calls.jsonl, rates.csv, usage.csv, report.md).
- [ ] Inspect `check_submission.py` → confirm the `grading/` folder layout it expects
      (run.json, ingestion.json, records.jsonl, membership.csv, ranking.csv,
      claims.csv, calls.jsonl, checkpoint_before.json, checkpoint_after.json).
- [ ] Read `manifest.json` → record exact source checksum + 18-month window boundaries.
- [ ] Verify ingestion profile matches: 660,622 rows / 13 empty / 159,701 missing
      app_version / 0 dup IDs / 484,189 distinct nonempty texts.
- [ ] Note the `cache_source_id` provenance field name the contract expects.
