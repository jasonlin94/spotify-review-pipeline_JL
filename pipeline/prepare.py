"""Stage 1 - Prepare / Ingest  (NO model calls).

Reads the full CSV, preserves every original ID and source value, profiles
quality, finds exact-duplicate texts, quarantines empty texts, and queues
pending work for the classifier.

Expected source columns (from the assignment data dictionary):
  review_id, review_text, review_rating, review_likes, app_version, review_timestamp

Outputs (under data/outputs/<run_id>/ by default):
  ingestion_report.json  - full-file profile + failure accounting
  data_manifest.json     - source identity (path, bytes, sha256, row counts)
  pending.jsonl          - {review_id, source_sha256, text_len, dup_group} per nonempty row
  quarantine.jsonl       - empty-text rows with reason=empty_review_text

Usage:
  python -m pipeline.prepare --input data/raw/spotify_reviews_18months.csv --run-id full01
  python -m pipeline.prepare --input cost/cost_100.csv --run-id pilot100 --limit 100

Counts are reported, never used to silently drop required reviews. The assignment
expects (for the full file): 660,622 rows, 13 empty texts, 159,701 missing
app_version, 0 repeated review_ids, 484,189 distinct nonempty texts. These are
asserted-as-warnings so an arbitrary supplied CSV still runs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from .hashing import text_sha
from .labels import SCHEMA_VERSION

# Allow very large review_text fields.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

EXPECTED = {
    "rows": 660_622,
    "empty_texts": 13,
    "missing_app_version": 159_701,
    "distinct_nonempty_texts": 484_189,
}


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def prepare(input_path: str, run_id: str, out_root: str = "data/outputs",
            limit: int | None = None) -> dict:
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(f"input CSV not found: {src}")

    out_dir = Path(out_root) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    n_rows = 0
    n_empty = 0
    n_missing_app_version = 0
    rating_hist: Counter[str] = Counter()
    seen_ids: set[str] = set()
    dup_ids: list[str] = []
    text_to_first_id: dict[str, str] = {}   # sha256(text) -> first review_id (cache source)
    text_counts: Counter[str] = Counter()
    min_ts: str | None = None
    max_ts: str | None = None

    pending_fp = (out_dir / "pending.jsonl").open("w", encoding="utf-8")
    quar_fp = (out_dir / "quarantine.jsonl").open("w", encoding="utf-8")

    try:
        with src.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            for row in reader:
                if limit is not None and n_rows >= limit:
                    break
                n_rows += 1

                rid = (row.get("review_id") or "").strip()
                text = row.get("review_text")
                if text is None:
                    text = ""

                if rid in seen_ids:
                    dup_ids.append(rid)
                else:
                    seen_ids.add(rid)

                rating_hist[(row.get("review_rating") or "").strip()] += 1
                if not (row.get("app_version") or "").strip():
                    n_missing_app_version += 1

                ts = (row.get("review_timestamp") or "").strip()
                if ts:
                    min_ts = ts if min_ts is None or ts < min_ts else min_ts
                    max_ts = ts if max_ts is None or ts > max_ts else max_ts

                if text.strip() == "":
                    n_empty += 1
                    quar_fp.write(json.dumps({
                        "review_id": rid,
                        "status": "quarantined",
                        "reason": "empty_review_text",
                        "attempts": 0,
                    }, ensure_ascii=False) + "\n")
                    continue

                th = text_sha(text)
                text_counts[th] += 1
                cache_source_id = text_to_first_id.setdefault(th, rid)

                pending_fp.write(json.dumps({
                    "review_id": rid,
                    "text_sha": th,
                    "text_len": len(text),
                    "is_dup": cache_source_id != rid,
                    "cache_source_id": cache_source_id,
                }, ensure_ascii=False) + "\n")
    finally:
        pending_fp.close()
        quar_fp.close()

    distinct_nonempty = len(text_to_first_id)
    nonempty = n_rows - n_empty

    report = {
        "run_id": run_id,
        "source_path": str(src),
        "source_columns": header,
        "rows_total": n_rows,
        "rows_nonempty": nonempty,
        "rows_empty": n_empty,
        "distinct_nonempty_texts": distinct_nonempty,
        "exact_text_reuse_savings": nonempty - distinct_nonempty,
        "duplicate_review_ids": len(dup_ids),
        "missing_app_version": n_missing_app_version,
        "rating_histogram": dict(sorted(rating_hist.items())),
        "timestamp_min": min_ts,
        "timestamp_max": max_ts,
        "quarantined": n_empty,
        "pending_nonempty": nonempty,
    }

    # Warn (not fail) when the full file does not match expected profile.
    warnings = []
    if limit is None:
        for k, exp in EXPECTED.items():
            got = {
                "rows": n_rows, "empty_texts": n_empty,
                "missing_app_version": n_missing_app_version,
                "distinct_nonempty_texts": distinct_nonempty,
            }[k]
            if got != exp:
                warnings.append(f"{k}: expected {exp}, got {got}")
    report["profile_warnings"] = warnings

    manifest = {
        "run_id": run_id,
        "source_path": str(src),
        "source_bytes": src.stat().st_size,
        "source_sha256": file_sha256(src),
        "rows_total": n_rows,
        "schema_version": SCHEMA_VERSION,
    }

    (out_dir / "ingestion_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "data_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if warnings:
        print("\n[WARN] profile differs from expected full-file values:", file=sys.stderr)
        for w in warnings:
            print("  -", w, file=sys.stderr)
    print(f"\nWrote: {out_dir}/{{ingestion_report,data_manifest}}.json, pending.jsonl, quarantine.jsonl")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 1: ingest + profile + dedup (no model).")
    ap.add_argument("--input", required=True, help="path to source CSV")
    ap.add_argument("--run-id", required=True, help="stable run identifier")
    ap.add_argument("--out-root", default="data/outputs")
    ap.add_argument("--limit", type=int, default=None, help="cap rows (for pilots/dev)")
    args = ap.parse_args()
    prepare(args.input, args.run_id, args.out_root, args.limit)


if __name__ == "__main__":
    main()
