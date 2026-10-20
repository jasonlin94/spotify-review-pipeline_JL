"""Quarantine recovery pass (recovery control; run AFTER the main classify run).

Re-processes `invalid_model_output` quarantines in SMALL batches. Isolating the
hard/garbage inputs (emoji-only, gibberish) from large batches lets the model
return a parseable line for most of them. Recovered records are appended to
enriched.jsonl + _completed.txt (enrich calls logged with phase="resume"); the
quarantine log is rewritten to keep only the still-unresolved entries
(empty_review_text + anything still invalid).

Safe to run only when no other process is writing the run dir (i.e. after the
main run finishes).

Usage:
  python -m pipeline.recover --input data/dataset/spotify_reviews_18months.csv \
      --run-dir data/outputs/full01 --batch-size 8
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import uuid
from pathlib import Path

from .classify import (build_prompt, extract_entities, extract_evidence_quote,
                       parse_line)
from .config import control, load_env
from .labels import SCHEMA_VERSION
from .model_client import make_client
from .schema import completed_record, make_label_config, validate_completed

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
PROMPT_VERSION = "classify-v1"


def load_rows(csv_path: Path, needed: set[str]) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rid = (row.get("review_id") or "").strip()
            if rid in needed:
                rows[rid] = row
                if len(rows) == len(needed):
                    break
    return rows


def recover(input_csv: str, run_dir: str, provider: str | None,
            batch_size: int = 8) -> dict:
    load_env()
    rd = Path(run_dir)
    qpath = rd / "quarantine.jsonl"
    entries = [json.loads(l) for l in qpath.read_text(encoding="utf-8").splitlines() if l.strip()]
    invalid = [e for e in entries if e.get("reason") == "invalid_model_output"]
    keep = [e for e in entries if e.get("reason") != "invalid_model_output"]
    target_ids = [e["review_id"] for e in invalid]
    if not target_ids:
        print("Nothing to recover (no invalid_model_output entries).")
        return {"recovered": 0, "still_quarantined": len(keep)}

    rows = load_rows(Path(input_csv), set(target_ids))
    client = make_client(provider, output_token_cap=control("OUTPUT_TOKEN_CAP", 1024))
    model_id = getattr(client, "model", "unknown")
    label_config = make_label_config(model_id, PROMPT_VERSION, SCHEMA_VERSION)

    enriched_fp = (rd / "enriched.jsonl").open("a", encoding="utf-8")
    done_fp = (rd / "_completed.txt").open("a", encoding="utf-8")
    calls_fp = (rd / "calls.jsonl").open("a", encoding="utf-8")

    recovered: set[str] = set()
    for i in range(0, len(target_ids), batch_size):
        chunk = [rid for rid in target_ids[i:i + batch_size] if rid in rows]
        batch = [(rid, rows[rid]["review_text"]) for rid in chunk]
        if not batch:
            continue
        prompt = build_prompt(batch)
        idx_to_rid = {str(j + 1): rid for j, (rid, _) in enumerate(batch)}
        outcome, in_tok, out_tok = "failed", 0, 0
        parsed = {}
        try:
            res = client.generate(prompt)
            outcome, in_tok, out_tok = "succeeded", res.input_tokens, res.output_tokens
            for line in res.text.splitlines():
                if "|" in line:
                    p = parse_line(line)
                    if p and p["id"] in idx_to_rid:
                        parsed[idx_to_rid[p["id"]]] = p
        except Exception as e:  # noqa: BLE001
            print(f"[warn] recover batch error: {type(e).__name__}: {e}", file=sys.stderr)
        calls_fp.write(json.dumps({
            "request_id": uuid.uuid4().hex, "role": "enrich",
            "review_ids": chunk, "model": model_id, "phase": "resume",
            "outcome": outcome, "label_config": label_config,
            "input_tokens": in_tok, "output_tokens": out_tok,
        }, ensure_ascii=False) + "\n")
        for rid, text in batch:
            p = parsed.get(rid)
            if p is None:
                continue
            row = rows[rid]
            rec = completed_record(
                row, topic=p["topic"], intent=p["intent"], sentiment=p["sentiment"],
                severity=p["severity"], entities=extract_entities(text),
                evidence_quote=extract_evidence_quote(text), needs_review=True,
                label_config=label_config)
            if validate_completed(rec, row):
                continue
            enriched_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            done_fp.write(rid + "\n")
            recovered.add(rid)
        enriched_fp.flush(); done_fp.flush(); calls_fp.flush()

    enriched_fp.close(); done_fp.close(); calls_fp.close()

    # Rewrite quarantine.jsonl: keep non-invalid + still-unrecovered invalids.
    still = keep + [e for e in invalid if e["review_id"] not in recovered]
    tmp = qpath.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in still),
                   encoding="utf-8")
    tmp.replace(qpath)

    out = {"attempted": len(target_ids), "recovered": len(recovered),
           "still_quarantined": len(still),
           "still_invalid": len(invalid) - len(recovered)}
    print(json.dumps(out, indent=2))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Recover invalid_model_output quarantines.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--batch-size", type=int, default=8)
    args = ap.parse_args()
    recover(args.input, args.run_dir, args.provider, args.batch_size)


if __name__ == "__main__":
    main()
