"""Build web/data/snapshot.json from saved analysis outputs.

The snapshot is the dashboard's data source for local dev AND the payload the
Postgres seed loads. The deployed backend reads Postgres; the snapshot keeps the
exact same shape so dev and prod render identically.

Usage:
  python -m db.make_snapshot --run-dir data/outputs/full01 --grading grading --out web/data/snapshot.json
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def read_json(p: Path, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def read_csv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--grading", required=True, help="grading folder (ranking/claims/records/memo_validation)")
    ap.add_argument("--out", default="web/data/snapshot.json")
    ap.add_argument("--cost", default="cost/pilot_meta.json")
    args = ap.parse_args()

    rd = Path(args.run_dir)
    g = Path(args.grading)

    ingest = read_json(rd / "ingestion_report.json", {})
    stats = read_json(rd / "classify_stats.json", {})
    titles = read_json(rd / "issue_titles.json", {})
    memo_val = read_json(g / "memo_validation.json", {})
    cost_meta = read_json(Path(args.cost), {})

    ranking = read_csv(g / "ranking.csv")
    membership = read_csv(g / "membership.csv")

    # Index completed records for drill-down (severity + quote per review).
    # Read run-dir enriched.jsonl (always plain) since grading/records.jsonl may be gzipped.
    rec_by_id: dict[str, dict] = {}
    for line in (Path(args.run_dir) / "enriched.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("status") == "completed":
            rec_by_id[r["review_id"]] = r

    issues: dict[str, dict] = {}
    for m in membership:
        iid, rid = m["issue_id"], m["review_id"]
        rec = rec_by_id.get(rid)
        if not rec:
            continue
        issues.setdefault(iid, {"issue_id": iid, "title": titles.get(iid, iid), "members": []})
        issues[iid]["members"].append({
            "review_id": rid, "severity": rec["severity"],
            "intent": rec["intent"], "sentiment": rec["sentiment"],
            "quote": rec["evidence_quote"],
        })
    for iid in issues:
        issues[iid]["members"].sort(key=lambda x: (-x["severity"], x["review_id"]))

    ranking_out = []
    for r in ranking:
        ranking_out.append({
            "rank": int(r["rank"]), "issue_id": r["issue_id"],
            "title": titles.get(r["issue_id"], r["issue_id"]),
            "complaint_count": int(r["complaint_count"]),
            "severity_sum": int(r["severity_sum"]),
            "mean_severity": r["mean_severity"],
            "priority_score": int(r["priority_score"]),
        })

    # Count completed/quarantined from the AUTHORITATIVE files, not the (possibly
    # stale) classify_stats.json left by an earlier/interrupted phase.
    enr = Path(args.run_dir) / "enriched.jsonl"
    completed_n = sum(1 for _ in enr.open(encoding="utf-8")) if enr.exists() else stats.get("completed")
    quar = Path(args.run_dir) / "quarantine.jsonl"
    quar_n = sum(1 for l in quar.open(encoding="utf-8") if l.strip()) if quar.exists() else stats.get("quarantined")

    overview = {
        "rows_total": ingest.get("rows_total"),
        "rows_nonempty": ingest.get("rows_nonempty"),
        "rows_empty": ingest.get("rows_empty"),
        "distinct_nonempty_texts": ingest.get("distinct_nonempty_texts"),
        "exact_text_reuse_savings": ingest.get("exact_text_reuse_savings"),
        "completed": completed_n,
        "dup_reused": stats.get("dup_reused"),
        "quarantined": quar_n,
        "model": stats.get("label_config"),
        "pilot_cost_usd_per_100": None,
        "cold_wall_s_100": cost_meta.get("cold_wall_s"),
        "warm_new_enrich_calls_100": cost_meta.get("warm_new_enrich_calls"),
    }

    memo = memo_val.get("memo") if isinstance(memo_val, dict) else None

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overview": overview,
        "ranking": ranking_out,
        "recommendation": memo,
        "issues": issues,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out} | issues={len(issues)} ranking={len(ranking_out)} "
          f"recommendation={'yes' if memo else 'no'}")


if __name__ == "__main__":
    main()
