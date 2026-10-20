"""Stage 3 - Verify  (independent second-opinion model task).

Re-labels a DECLARED random sample of completed records using a DIFFERENT prompt,
seeing ONLY the original review text + rubric (never the enricher's prediction).
Code then compares verifier vs enricher and writes a disagreement report. This is
a separate model role (role="verify" in calls.jsonl), satisfying the contract's
independent-verification requirement.

Sampling is deterministic: lowest sha256(seed+":"+review_id) over completed
records. The sample size/fraction and seed are declared in the output.

Outputs under <run_dir>/:
  verifier_predictions.jsonl - {review_id, topic, intent, severity}
  verify_report.json         - sample declaration, agreement rates, disagreements

Usage:
  python -m pipeline.verify --run-dir data/outputs/full01 --sample 300 --seed verify-v1
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import uuid
from pathlib import Path

from .config import load_env
from .labels import INTENTS, SEVERITY, TOPICS
from .model_client import ModelError, make_client

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def load_texts(csv_path: Path, needed: set[str]) -> dict[str, str]:
    m: dict[str, str] = {}
    with csv_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rid = (row.get("review_id") or "").strip()
            if rid in needed:
                m[rid] = row.get("review_text") or ""
                if len(m) == len(needed):
                    break
    return m

VERIFY_PROMPT_VERSION = "verify-v1"
# Deliberately different wording from the enricher (independent instructions).
VERIFY_HEADER = """You are an independent reviewer auditing Spotify review labels.
Read each review and decide, from the text alone, the single best:
  topic  : access usability playback downloads catalog billing support other
  intent : cancellation complaint request praise unclear  (cancellation wins ties)
  severity: 1 none/praise/request, 2 minor annoyance, 3 degraded, 4 core task blocked,
            5 serious financial/privacy/data harm
Output exactly one line per review: index|topic|intent|severity
No other text.

Reviews:
"""


def sample_ids(records: list[dict], n: int, seed: str) -> list[str]:
    scored = sorted(records, key=lambda r: hashlib.sha256(
        (seed + ":" + r["review_id"]).encode()).hexdigest())
    return [r["review_id"] for r in scored[:n]]


def parse_line(line: str):
    parts = [p.strip() for p in line.split("|")]
    if len(parts) != 4:
        return None
    idx, topic, intent, sev = parts
    if topic not in TOPICS or intent not in INTENTS:
        return None
    try:
        s = int(sev)
    except ValueError:
        return None
    if s not in SEVERITY:
        return None
    return {"idx": idx, "topic": topic, "intent": intent, "severity": s}


def verify(run_dir: str, input_csv: str, sample: int, seed: str,
           provider: str | None = None, batch_size: int = 50) -> dict:
    load_env()
    rd = Path(run_dir)
    recs = [json.loads(l) for l in (rd / "enriched.jsonl").read_text(
        encoding="utf-8").splitlines() if l.strip()]
    completed = [r for r in recs if r.get("status") == "completed"]
    by_id = {r["review_id"]: r for r in completed}

    ids = sample_ids(completed, min(sample, len(completed)), seed)
    texts = load_texts(Path(input_csv), set(ids))  # ORIGINAL text, independent of enricher
    client = make_client(provider)
    model_id = getattr(client, "model", "unknown")
    label_config = f"{model_id}+{VERIFY_PROMPT_VERSION}+schema-v1"

    preds: dict[str, dict] = {}
    calls_fp = (rd / "calls.jsonl").open("a", encoding="utf-8")
    vpred_fp = (rd / "verifier_predictions.jsonl").open("w", encoding="utf-8")

    for i in range(0, len(ids), batch_size):
        chunk = [rid for rid in ids[i:i + batch_size] if rid in texts]
        batch = [(rid, texts[rid]) for rid in chunk]  # ORIGINAL review text
        idx_to_rid = {str(j + 1): rid for j, (rid, _) in enumerate(batch)}
        prompt = VERIFY_HEADER + "\n".join(
            f"{j+1}: {txt.replace(chr(10),' ')[:500]}" for j, (_, txt) in enumerate(batch)) + "\n"
        outcome, in_tok, out_tok = "failed", 0, 0
        try:
            res = client.generate(prompt)
            outcome, in_tok, out_tok = "succeeded", res.input_tokens, res.output_tokens
            for line in res.text.splitlines():
                if "|" in line:
                    p = parse_line(line)
                    if p and p["idx"] in idx_to_rid:
                        rid = idx_to_rid[p["idx"]]
                        preds[rid] = p
                        vpred_fp.write(json.dumps({
                            "review_id": rid, "topic": p["topic"],
                            "intent": p["intent"], "severity": p["severity"],
                        }, ensure_ascii=False) + "\n")
        except ModelError as e:
            print(f"[warn] verify batch failed: {e}")
        calls_fp.write(json.dumps({
            "request_id": uuid.uuid4().hex, "role": "verify",
            "review_ids": list(chunk), "model": model_id, "phase": "initial",
            "outcome": outcome, "label_config": label_config,
            "input_tokens": in_tok, "output_tokens": out_tok,
        }, ensure_ascii=False) + "\n")
    calls_fp.close(); vpred_fp.close()

    # Compare verifier vs enricher.
    topic_agree = intent_agree = sev_exact = 0
    sev_abs = 0
    disagreements = []
    compared = 0
    for rid, vp in preds.items():
        ep = by_id[rid]
        compared += 1
        t = vp["topic"] == ep["topic"]
        it = vp["intent"] == ep["intent"]
        se = vp["severity"] == ep["severity"]
        topic_agree += t; intent_agree += it; sev_exact += se
        sev_abs += abs(vp["severity"] - ep["severity"])
        if not (t and it and se):
            if len(disagreements) < 50:
                disagreements.append({
                    "review_id": rid,
                    "enricher": {"topic": ep["topic"], "intent": ep["intent"], "severity": ep["severity"]},
                    "verifier": {"topic": vp["topic"], "intent": vp["intent"], "severity": vp["severity"]},
                })

    def frac(a):
        return round(a / compared, 6) if compared else None

    report = {
        "sample_declared": len(ids), "verified": compared, "seed": seed,
        "sampling": "lowest sha256(seed+':'+review_id) over completed records",
        "verify_model": model_id, "verify_prompt_version": VERIFY_PROMPT_VERSION,
        "topic_agreement": frac(topic_agree),
        "intent_agreement": frac(intent_agree),
        "severity_exact_agreement": frac(sev_exact),
        "severity_mae": round(sev_abs / compared, 6) if compared else None,
        "disagreement_count": len(disagreements) if compared else 0,
        "disagreements_sample": disagreements,
    }
    full_disagreements = compared - sum(
        1 for rid, vp in preds.items()
        if vp["topic"] == by_id[rid]["topic"] and vp["intent"] == by_id[rid]["intent"]
        and vp["severity"] == by_id[rid]["severity"])
    report["disagreement_count"] = full_disagreements
    report["disagreements_shown"] = len(disagreements)
    (rd / "verify_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "disagreements_sample"},
                     indent=2, ensure_ascii=False))
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 3: independent verification sample.")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--input", required=True, help="source CSV (original texts)")
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--seed", default="verify-v1")
    ap.add_argument("--provider", default=None)
    args = ap.parse_args()
    verify(args.run_dir, args.input, args.sample, args.seed, args.provider)


if __name__ == "__main__":
    main()
