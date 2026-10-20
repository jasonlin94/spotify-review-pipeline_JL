"""Planted-error test (synthetic; excluded from business aggregates).

Takes synthetic reviews whose correct label is obvious, plants a DELIBERATELY
WRONG "enricher" label on each, then runs the independent verifier (re-labels
from the text alone). The verification stage should DISAGREE with every planted
wrong label - demonstrating that the verifier catches enricher mistakes.

A case PASSES when the verifier's independent label differs from the planted
wrong label on at least one field. Results -> evals/planted_error_results.json.
Synthetic PE- ids never enter grading/records.jsonl.

Usage:
  python -m evals.planted_error
"""
from __future__ import annotations

import json
from pathlib import Path

from pipeline.config import load_env
from pipeline.model_client import make_client
from pipeline.verify import VERIFY_HEADER, parse_line

CASES = [
    {"id": "PE-001",
     "text": "Can't log in after the update, my password keeps getting rejected.",
     "true": {"topic": "access", "intent": "complaint", "severity": 4},
     "planted_wrong": {"topic": "playback", "intent": "praise", "severity": 1}},
    {"id": "PE-002",
     "text": "I was charged twice for Premium this month and want a refund.",
     "true": {"topic": "billing", "intent": "complaint", "severity": 4},
     "planted_wrong": {"topic": "downloads", "intent": "praise", "severity": 1}},
    {"id": "PE-003",
     "text": "Downloaded songs stop playing the moment I go offline.",
     "true": {"topic": "downloads", "intent": "complaint", "severity": 3},
     "planted_wrong": {"topic": "support", "intent": "cancellation", "severity": 5}},
]


def run() -> dict:
    load_env()
    client = make_client()
    batch = [(c["id"], c["text"]) for c in CASES]
    idx_to_id = {str(j + 1): c["id"] for j, c in enumerate(CASES)}
    prompt = VERIFY_HEADER + "\n".join(
        f"{j+1}: {c['text']}" for j, c in enumerate(CASES)) + "\n"
    res = client.generate(prompt)
    verifier = {}
    for line in res.text.splitlines():
        if "|" in line:
            p = parse_line(line)
            if p and p["idx"] in idx_to_id:
                verifier[idx_to_id[p["idx"]]] = p

    results = []
    detected = 0
    for c in CASES:
        v = verifier.get(c["id"])
        if v is None:
            results.append({"id": c["id"], "status": "no_verifier_output", "detected": False})
            continue
        vp = {"topic": v["topic"], "intent": v["intent"], "severity": v["severity"]}
        disagrees_with_planted = any(vp[k] != c["planted_wrong"][k] for k in vp)
        matches_true = all(vp[k] == c["true"][k] for k in vp)
        detected += disagrees_with_planted
        results.append({
            "id": c["id"], "planted_wrong": c["planted_wrong"], "true_label": c["true"],
            "verifier_independent": vp,
            "planted_error_detected": disagrees_with_planted,
            "verifier_matches_truth": matches_true,
        })

    out = {"test": "planted_error", "model": getattr(client, "model", "?"),
           "cases": len(CASES), "planted_errors_detected": detected,
           "note": "PASS = verifier disagrees with the planted wrong label (catches it). "
                   "Synthetic PE- ids are excluded from business aggregates.",
           "results": results}
    Path("evals").mkdir(exist_ok=True)
    Path("evals/planted_error_results.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
