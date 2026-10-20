"""Convert the hand-labeled golden CSV into the grader's gold.json.

Input: a copy of golden_50_to_label.csv with the label columns filled
(topic, intent, sentiment, severity, evidence_quote, needs_review). A cell may
list several accepted labels separated by '|' for genuinely ambiguous cases.

Output: gold.json in check_submission.py's expected shape:
  {"version": ..., "cases": [{"review_id","accepted_topic":[...],
    "accepted_intent":[...],"accepted_severity":[int,...],"status":"approved","reviewer":...}]}

The hand labels here are used ONLY to build gold.json for scoring; they are never
fed to any model (that would violate the contract).

Usage:
  python -m evals.make_gold --labeled evals/golden_50_labeled.csv \
      --reviewer "Jason Lin" --out evals/gold.json
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from pipeline.labels import INTENTS, TOPICS

LABEL_COLS = ("topic", "intent", "severity")


def cell_list(v: str) -> list[str]:
    return [x.strip() for x in str(v).split("|") if x.strip()]


def convert(labeled: str, reviewer: str, version: str) -> dict:
    rows = []
    with Path(labeled).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    cases = []
    incomplete = []
    for row in rows:
        rid = (row.get("review_id") or "").strip()
        topics = cell_list(row.get("topic", ""))
        intents = cell_list(row.get("intent", ""))
        sevs_raw = cell_list(row.get("severity", ""))
        if not (rid and topics and intents and sevs_raw):
            incomplete.append(rid or "<no id>")
            continue
        bad = [t for t in topics if t not in TOPICS] + [i for i in intents if i not in INTENTS]
        try:
            sevs = [int(s) for s in sevs_raw]
        except ValueError:
            incomplete.append(rid + " (severity not int)")
            continue
        if bad or any(s < 1 or s > 5 for s in sevs):
            incomplete.append(rid + f" (invalid labels: {bad or sevs})")
            continue
        cases.append({
            "review_id": rid,
            "accepted_topic": topics,
            "accepted_intent": intents,
            "accepted_severity": sevs,
            "status": "approved",
            "reviewer": reviewer,
        })
    return {"version": version, "cases": cases, "_incomplete": incomplete,
            "_total_rows": len(rows)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labeled", default="evals/golden_50_labeled.csv")
    ap.add_argument("--reviewer", required=True)
    ap.add_argument("--version", default="golden-v1")
    ap.add_argument("--out", default="evals/gold.json")
    args = ap.parse_args()

    gold = convert(args.labeled, args.reviewer, args.version)
    incomplete = gold.pop("_incomplete")
    total = gold.pop("_total_rows")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.out}: {len(gold['cases'])}/{total} approved cases.")
    if incomplete:
        print(f"[!] {len(incomplete)} rows not yet usable: {incomplete[:5]}"
              + (" ..." if len(incomplete) > 5 else ""))
        print("    Official golden scoring needs all 50 filled with valid labels.")


if __name__ == "__main__":
    main()
