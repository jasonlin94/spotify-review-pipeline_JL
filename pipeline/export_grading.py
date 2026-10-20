"""Assemble the grading/ folder required by GRADING_CONTRACT.md.

Combines saved stage outputs into the compact adapter the grader's
check_submission.py audits. Produces:
  run.json, records.jsonl, membership.csv, ranking.csv, claims.csv,
  calls.jsonl, checkpoint_before.json, checkpoint_after.json
and runs the provided `check_submission.py profile` to make ingestion.json.

records.jsonl: exactly one line per source ID present in our outputs -
completed records from enriched.jsonl, quarantined IDs with a reason and the
row's source_sha256 (recomputed from the CSV).

claims.csv: one claim per metric for each ranked issue (the memo cites these
claim IDs). Values are copied from ranking.csv so they match the checker's
recomputation exactly.

Usage:
  python -m pipeline.export_grading --run-dir data/outputs/full01 \
      --analysis-csv data/dataset/spotify_reviews_18months.csv \
      --full-csv data/dataset/spotify_reviews_18months.csv \
      --checker data/dataset/check_submission.py --out grading
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

from .hashing import row_sha

VERSION = "a5-audit-v1"


def file_sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def export(run_dir: str, analysis_csv: str, full_csv: str, checker: str,
           out: str, allow_multi_issue: bool = False) -> dict:
    rd = Path(run_dir)
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)

    enriched = read_jsonl(rd / "enriched.jsonl")
    quarantine = read_jsonl(rd / "quarantine.jsonl")

    # Dedup records by review_id (keep last); separate completed vs quarantined.
    completed = {r["review_id"]: r for r in enriched if r.get("status") == "completed"}
    quar_ids = {q["review_id"]: q.get("reason", "unspecified")
                for q in quarantine if q["review_id"] not in completed}

    # Compute source_sha256 for quarantined ids from the CSV.
    quar_rows: dict[str, dict] = {}
    if quar_ids:
        csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
        with Path(analysis_csv).open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                rid = (row.get("review_id") or "").strip()
                if rid in quar_ids:
                    quar_rows[rid] = row

    # records.jsonl
    records_path = out_dir / "records.jsonl"
    with records_path.open("w", encoding="utf-8") as f:
        for rid, rec in completed.items():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        for rid, reason in quar_ids.items():
            row = quar_rows.get(rid)
            if row is None:
                continue
            f.write(json.dumps({
                "review_id": rid, "source_sha256": row_sha(row),
                "status": "quarantined", "reason": reason,
            }, ensure_ascii=False) + "\n")

    # run.json
    run = {
        "version": VERSION,
        "analysis_count": sum(1 for _ in csv.DictReader(
            Path(analysis_csv).open(encoding="utf-8", newline=""))),
        "analysis_sha256": file_sha256(Path(analysis_csv)),
        "classification_input_fields": ["review_text"],
        "allow_multi_issue": allow_multi_issue,
    }
    (out_dir / "run.json").write_text(json.dumps(run), encoding="utf-8")

    # membership.csv, ranking.csv (copy from run-dir)
    for name in ("membership.csv", "ranking.csv"):
        src = rd / name
        if src.exists():
            (out_dir / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    # claims.csv from ranking.csv (one claim per metric per issue)
    claims_path = out_dir / "claims.csv"
    ranking = []
    if (rd / "ranking.csv").exists():
        with (rd / "ranking.csv").open(encoding="utf-8-sig", newline="") as f:
            ranking = list(csv.DictReader(f))
    with claims_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["claim_id", "issue_id", "metric", "value"])
        n = 0
        for row in ranking:
            for metric in ("complaint_count", "severity_sum", "mean_severity", "priority_score"):
                n += 1
                w.writerow([f"C{n}", row["issue_id"], metric, row[metric]])

    # calls.jsonl (copy)
    calls_src = rd / "calls.jsonl"
    if calls_src.exists():
        (out_dir / "calls.jsonl").write_text(calls_src.read_text(encoding="utf-8"), encoding="utf-8")

    # checkpoints (copy if the run produced them; else leave for resume demo)
    for name in ("checkpoint_before.json", "checkpoint_after.json"):
        src = rd / name
        if src.exists():
            (out_dir / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    # ingestion.json via the provided helper (deterministic full-file profile)
    ing = out_dir / "ingestion.json"
    subprocess.run([sys.executable, checker, "profile", "--full", full_csv,
                    "--out", str(ing)], check=True)

    summary = {"completed": len(completed), "quarantined": len(quar_ids),
               "records": len(completed) + len(quar_ids), "issues_ranked": len(ranking),
               "analysis_count": run["analysis_count"], "out": str(out_dir)}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Assemble grading/ folder.")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--analysis-csv", required=True)
    ap.add_argument("--full-csv", required=True)
    ap.add_argument("--checker", required=True)
    ap.add_argument("--out", default="grading")
    ap.add_argument("--allow-multi-issue", action="store_true")
    args = ap.parse_args()
    export(args.run_dir, args.analysis_csv, args.full_csv, args.checker,
           args.out, args.allow_multi_issue)


if __name__ == "__main__":
    main()
