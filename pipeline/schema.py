"""Enriched-record schema + validation (code owns correctness, not the model).

Every completed record carries:
  review_id, source_sha256, status, topic, intent, sentiment (-1..1),
  severity (int 1..5), entities, evidence_quote (exact source substring),
  needs_review, label_config.

`validate_record` enforces required keys, types, allowed labels, numeric ranges,
exact source ID, and quote membership. A record that fails is retried once by the
orchestrator, then quarantined. NOTE: a *valid* record can still be *wrong* — a
real quote may not support the chosen label; that is what the verifier + golden
set catch, not this function.

Exact field names / export order will be reconciled with GRADING_CONTRACT.md
(records.jsonl) once the dataset ZIP is available.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .labels import (
    ALLOWED_STATUSES,
    INTENTS,
    LABEL_CONFIG_VERSION,
    SENTIMENT_MAX,
    SENTIMENT_MIN,
    SEVERITY,
    TOPICS,
)

REQUIRED_KEYS = [
    "review_id", "source_sha256", "status", "topic", "intent",
    "sentiment", "severity", "entities", "evidence_quote",
    "needs_review", "label_config",
]


def source_sha256(review_text: str) -> str:
    """Hash of the ORIGINAL review text (UTF-8). The exact hashing rule is fixed
    by GRADING_CONTRACT.md; we default to sha256 of the raw bytes and will
    confirm (e.g. whether newlines are normalized) against the contract."""
    return hashlib.sha256(review_text.encode("utf-8")).hexdigest()


class ValidationError(Exception):
    pass


def validate_record(rec: dict[str, Any], review_text: str, review_id: str) -> list[str]:
    """Return a list of problems; empty list == valid."""
    errs: list[str] = []

    for k in REQUIRED_KEYS:
        if k not in rec:
            errs.append(f"missing key: {k}")
    if errs:
        return errs  # can't check further without keys

    if str(rec["review_id"]) != str(review_id):
        errs.append("review_id does not match source ID")

    if rec["source_sha256"] != source_sha256(review_text):
        errs.append("source_sha256 does not match original text")

    if rec["status"] not in ALLOWED_STATUSES:
        errs.append(f"bad status: {rec['status']!r}")

    if rec["topic"] not in TOPICS:
        errs.append(f"bad topic: {rec['topic']!r}")

    if rec["intent"] not in INTENTS:
        errs.append(f"bad intent: {rec['intent']!r}")

    s = rec["sentiment"]
    if not isinstance(s, (int, float)) or not (SENTIMENT_MIN <= s <= SENTIMENT_MAX):
        errs.append(f"sentiment out of range: {s!r}")

    sev = rec["severity"]
    if not isinstance(sev, int) or sev not in SEVERITY:
        errs.append(f"severity must be int 1..5: {sev!r}")

    if not isinstance(rec["entities"], list):
        errs.append("entities must be a list")

    # evidence_quote must be an exact substring of the original text.
    q = rec["evidence_quote"]
    if not isinstance(q, str):
        errs.append("evidence_quote must be a string")
    elif q and q not in review_text:
        errs.append("evidence_quote is not an exact substring of source text")

    if not isinstance(rec["needs_review"], bool):
        errs.append("needs_review must be a bool")

    if rec["label_config"] != LABEL_CONFIG_VERSION:
        errs.append(
            f"label_config mismatch: {rec['label_config']!r} != {LABEL_CONFIG_VERSION!r}"
        )

    return errs


def new_record(review_id: str, review_text: str, **fields: Any) -> dict[str, Any]:
    """Assemble a record with provenance fields filled in by code."""
    rec = {
        "review_id": str(review_id),
        "source_sha256": source_sha256(review_text),
        "label_config": LABEL_CONFIG_VERSION,
    }
    rec.update(fields)
    return rec
