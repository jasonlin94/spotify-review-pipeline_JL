"""Enriched-record schema + validation (code owns correctness, not the model).

Aligned with GRADING_CONTRACT.md / check_submission.py. A completed record:
  review_id, source_sha256 (ROW hash of 6 fields), status, topic, intent,
  sentiment (-1..1), severity (int 1..5), entities (list[str]), evidence_quote
  (exact source substring), needs_review (bool), label_config (nonempty str).

`validate_record` enforces exactly what the checker's `audit` requires so a valid
record never trips invalid_schema / source_mismatch / unsupported_quote.
A valid record can still be WRONG (quote may not support the label) -> verifier.
"""
from __future__ import annotations

from typing import Any

from .hashing import row_sha
from .labels import INTENTS, SEVERITY, TOPICS

REQUIRED_KEYS = [
    "review_id", "source_sha256", "status", "topic", "intent",
    "sentiment", "severity", "entities", "evidence_quote",
    "needs_review", "label_config",
]


def make_label_config(model: str, prompt_version: str, schema_version: str) -> str:
    return f"{model}+{prompt_version}+{schema_version}"


def validate_completed(rec: dict[str, Any], row: dict[str, Any]) -> list[str]:
    """Return problems for a COMPLETED record; empty list == valid.

    `row` is the original CSV row (all 6 fields) so we can recompute the row hash
    and confirm the quote is a substring of the exact source text.
    """
    errs: list[str] = []
    for k in REQUIRED_KEYS:
        if k not in rec:
            errs.append(f"missing key: {k}")
    if errs:
        return errs

    if str(rec["review_id"]) != str(row["review_id"]):
        errs.append("review_id mismatch")
    if rec["source_sha256"] != row_sha(row):
        errs.append("source_sha256 != row_sha")
    if rec["topic"] not in TOPICS:
        errs.append(f"bad topic: {rec['topic']!r}")
    if rec["intent"] not in INTENTS:
        errs.append(f"bad intent: {rec['intent']!r}")

    s = rec["sentiment"]
    if type(s) not in (int, float) or not (-1 <= s <= 1):
        errs.append(f"sentiment out of range: {s!r}")
    if type(rec["severity"]) is not int or rec["severity"] not in SEVERITY:
        errs.append(f"severity must be int 1..5: {rec['severity']!r}")

    ents = rec["entities"]
    if not isinstance(ents, list) or not all(isinstance(x, str) and x.strip() for x in ents):
        errs.append("entities must be a list of nonempty strings")

    q = rec["evidence_quote"]
    if not isinstance(q, str) or not q.strip():
        errs.append("evidence_quote must be a nonempty string")
    elif q not in row["review_text"]:
        errs.append("evidence_quote is not an exact substring of source text")

    if type(rec["needs_review"]) is not bool:
        errs.append("needs_review must be a bool")
    if not isinstance(rec["label_config"], str) or not rec["label_config"].strip():
        errs.append("label_config must be a nonempty string")
    return errs


def completed_record(row: dict[str, Any], *, topic: str, intent: str,
                     sentiment: float, severity: int, entities: list[str],
                     evidence_quote: str, needs_review: bool,
                     label_config: str) -> dict[str, Any]:
    return {
        "review_id": str(row["review_id"]),
        "source_sha256": row_sha(row),
        "status": "completed",
        "topic": topic,
        "intent": intent,
        "sentiment": sentiment,
        "severity": severity,
        "entities": entities,
        "evidence_quote": evidence_quote,
        "needs_review": needs_review,
        "label_config": label_config,
    }


def quarantined_record(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "review_id": str(row["review_id"]),
        "source_sha256": row_sha(row),
        "status": "quarantined",
        "reason": reason,
    }
