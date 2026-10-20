"""Golden-set evaluation switch.

- If the hand-labeled file is missing or not fully filled -> prints PENDING and
  exits 0 (nothing to score yet; the pipeline does not block on it).
- If it is complete -> classifies the 50 golden reviews (their original texts,
  never their answer labels), builds a reference and runs the grader's
  check_submission.py with --gold, then prints the official golden metrics
  (topic/intent agreement, severity exact agreement + MAE, macro F1).

The golden answer labels are used ONLY to build gold.json for scoring.

Usage:
  python -m evals.run_golden --reviewer "Jason Lin"
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from evals.make_gold import convert

DATASET = Path("data/dataset")
GOLDEN_TEMPLATE = DATASET / "golden_50_to_label.csv"   # 6 source fields + blank labels
CHECKER = DATASET / "check_submission.py"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labeled", default="evals/golden_50_labeled.csv")
    ap.add_argument("--reviewer", default="")
    ap.add_argument("--run-dir", default="data/outputs/golden50")
    args = ap.parse_args()
    py = sys.executable

    labeled = Path(args.labeled)
    if not labeled.exists():
        print(f"PENDING: {labeled} not found. Fill the 50 labels first "
              f"(copy {GOLDEN_TEMPLATE} and complete topic/intent/severity/...).")
        return
    gold = convert(str(labeled), args.reviewer or "unspecified", "golden-v1")
    if gold["_incomplete"] or len(gold["cases"]) < gold["_total_rows"]:
        print(f"PENDING: {len(gold['cases'])}/{gold['_total_rows']} rows labeled. "
              "Official scoring needs all 50 valid.")
        return
    if not args.reviewer:
        print("Provide --reviewer to mark the labels as approved for official scoring.")
        return

    # Write gold.json
    gold2 = {"version": gold["version"], "cases": gold["cases"]}
    Path("evals/gold.json").write_text(json.dumps(gold2, ensure_ascii=False, indent=2), encoding="utf-8")

    # Classify the golden reviews (original texts only), then export a grading folder.
    rd = Path(args.run_dir)
    subprocess.run([py, "-m", "pipeline.prepare", "--input", str(GOLDEN_TEMPLATE),
                    "--run-id", rd.name, "--out-root", str(rd.parent)], check=True)
    subprocess.run([py, "-m", "pipeline.classify", "--input", str(GOLDEN_TEMPLATE),
                    "--run-dir", str(rd)], check=True)
    subprocess.run([py, "-m", "pipeline.export_grading", "--run-dir", str(rd),
                    "--analysis-csv", str(GOLDEN_TEMPLATE), "--full-csv", str(GOLDEN_TEMPLATE),
                    "--checker", str(CHECKER), "--out", str(rd / "grading")], check=True)

    # Reference + check with --gold
    subprocess.run([py, str(CHECKER), "reference", "--full", str(GOLDEN_TEMPLATE),
                    "--analysis", str(GOLDEN_TEMPLATE), "--out", str(rd / "ref.json")], check=True)
    subprocess.run([py, str(CHECKER), "check", "--reference", str(rd / "ref.json"),
                    "--submission", str(rd / "grading"), "--gold", "evals/gold.json",
                    "--out", str(rd / "golden_selfcheck.json")], check=True)

    result = json.loads((rd / "golden_selfcheck.json").read_text(encoding="utf-8"))
    q = result.get("quality", {})
    (Path("evals") / "golden_results.json").write_text(
        json.dumps(q, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n=== GOLDEN RESULTS ===")
    print(json.dumps({k: q.get(k) for k in
                      ("status", "official", "approved_cases", "agreement",
                       "severity_mae_on_valid_predictions", "singleton_metrics")},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
