"""Row/text hashing that byte-for-byte matches the grader's check_submission.py.

The grading `source_sha256` is SHA-256 of the canonical UTF-8 compact JSON of the
SIX original field strings, in this exact order. We MUST reproduce the checker's
`canonical` + `row_sha` precisely or every record fails `source_mismatch`.

Dedup uses a SEPARATE text hash (review_text only), because two rows with
identical text still have different row hashes (different review_id, etc.).
"""
from __future__ import annotations

import hashlib
import json

# Exact field order from check_submission.py: FIELDS
FIELDS = ("review_id", "review_text", "review_rating",
          "review_likes", "app_version", "review_timestamp")


def canonical(value) -> str:
    # Mirrors check_submission.canonical exactly.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True, allow_nan=False)


def row_sha(row: dict) -> str:
    """SHA-256 of canonical([row[k] for k in FIELDS]). No whitespace/accent norm."""
    return hashlib.sha256(
        canonical([row[k] for k in FIELDS]).encode("utf-8")).hexdigest()


def text_sha(review_text: str) -> str:
    """Dedup key: hash of the exact review_text (not a grading field)."""
    return hashlib.sha256(review_text.encode("utf-8")).hexdigest()
