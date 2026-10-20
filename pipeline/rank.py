"""Stage 5 - Rank  (pure code; NO model; deterministic & reproducible).

Regenerates the baseline ranking from saved membership.csv + enriched.jsonl,
mirroring check_submission.py EXACTLY so the grader's recomputation matches:

  complaint_count = membership count for the issue
  severity_sum    = sum of member severities
  mean_severity   = Decimal(severity_sum)/Decimal(count), 6 dp, ROUND_HALF_UP
  priority_score  = severity_sum   (== count x mean severity, no float loss)
  order: descending priority_score, then ascending issue_id; rank from 1

This runs with no API key or model call (the offline reranking requirement).

Usage:
  python -m pipeline.rank --run-dir data/outputs/full01
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from .labels import RANKABLE_INTENTS


def mean_string(total: int, n: int) -> str:
    return str((Decimal(total) / Decimal(n)).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP))


def load_severity(run_dir: Path) -> dict[str, int]:
    sev: dict[str, int] = {}
    for line in (run_dir / "enriched.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("status") == "completed" and r["intent"] in RANKABLE_INTENTS:
            sev[r["review_id"]] = r["severity"]
    return sev


def rank(run_dir: str) -> list[dict]:
    rd = Path(run_dir)
    sev = load_severity(rd)

    members: dict[str, list[int]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    with (rd / "membership.csv").open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            iid, rid = row["issue_id"], row["review_id"]
            if (iid, rid) in seen or rid not in sev:
                continue
            seen.add((iid, rid))
            members[iid].append(sev[rid])

    calculated = []
    for iid, vals in members.items():
        calculated.append({
            "issue_id": iid,
            "complaint_count": len(vals),
            "severity_sum": sum(vals),
            "mean_severity": mean_string(sum(vals), len(vals)),
            "priority_score": sum(vals),
        })
    calculated.sort(key=lambda x: (-x["priority_score"], x["issue_id"]))
    for i, row in enumerate(calculated, 1):
        row["rank"] = i

    cols = ["rank", "issue_id", "complaint_count", "severity_sum",
            "mean_severity", "priority_score"]
    with (rd / "ranking.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for row in calculated:
            w.writerow([row[c] for c in cols])

    print(json.dumps(calculated, indent=2, ensure_ascii=False))
    return calculated


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 5: deterministic baseline ranking.")
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()
    rank(args.run_dir)


if __name__ == "__main__":
    main()
