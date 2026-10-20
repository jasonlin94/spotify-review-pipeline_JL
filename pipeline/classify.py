"""Stage 2 - Classify / Enrich  (model: Gemini flash-lite; batches <= 50).

Consumes pending.jsonl (from Stage 1) + the source CSV. For each DISTINCT text it
asks the model for a compact label line; code fills provenance + extraction fields
(source_sha256 = row_sha of the 6 original fields) and validates against the
grading contract. Duplicate texts reuse the distinct record's label fields (no
model call) with their own review_id/source_sha256 and a cache_source_id pointer.

Model returns ONE line per review:  id|topic|intent|severity|sentiment
Invalid/unparseable output is retried ONCE, then quarantined. Results + statuses
are saved atomically after each batch so an interrupted run resumes without
re-paying for completed IDs (phase "initial" vs "resume" is logged in calls.jsonl).

Outputs under <run_dir>/:
  enriched.jsonl   - one completed record per review_id (contract shape)
  quarantine.jsonl - appended classify failures (empties come from export step)
  calls.jsonl      - grading-format model-call log (role=enrich)
  _completed.txt   - resume index (review_ids done)

Usage:
  python -m pipeline.classify --input data/dataset/spotify_reviews_18months.csv \
      --run-dir data/outputs/full01 --limit 100000
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import uuid
from pathlib import Path

from .config import control, load_env
from .hashing import row_sha
from .labels import INTENTS, SCHEMA_VERSION, SEVERITY, TOPICS
from .model_client import ModelError, make_client
from .schema import completed_record, make_label_config, validate_completed

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

SENTIMENT_MAP = {"-1": -1.0, "-0.5": -0.5, "0": 0.0, "0.5": 0.5, "1": 1.0}
FEATURE_LEXICON = [
    "premium", "offline", "download", "login", "log in", "account", "ads",
    "advertisement", "playlist", "shuffle", "podcast", "lyrics", "search",
    "subscription", "price", "charge", "crash", "buffering", "sleep timer",
]
PROMPT_VERSION = "classify-v1"
PROMPT_HEADER = """Classify each Spotify app review. Output ONE line per review, EXACT format:
id|topic|intent|severity|sentiment

topic (choose ONE): access(login/account) usability(controls/navigation/ads) \
playback(playback fail/crash/lag/audio) downloads(offline/saved music) \
catalog(content/search/recommendations/lyrics) billing(price/charges/paywall/premium) \
support(support contact/response) other
intent (choose ONE, precedence cancellation>complaint>request>praise>unclear)
severity: integer 1-5 (1 none/praise/feature-request, 2 annoyance/cosmetic, \
3 degraded function, 4 core task blocked, 5 serious financial/privacy/data harm)
sentiment: one of -1 -0.5 0 0.5 1
Rules: stars/anger/cancellation alone do not set severity. A paid-plan mention \
alone is not billing; a subscription failing to activate is billing. Output ONLY \
the lines, no header, no extra text.

Reviews:
"""


def extract_evidence_quote(text: str, max_len: int = 160) -> str:
    t = text.strip()
    if 0 < len(t) <= max_len:
        return t
    low = text.lower()
    for kw in FEATURE_LEXICON:
        idx = low.find(kw)
        if idx != -1:
            start = max(0, idx - 40)
            seg = text[start:start + max_len].strip()
            if seg:
                return seg
    seg = text[:max_len].strip()
    return seg or text[:max_len]


def extract_entities(text: str) -> list[str]:
    low = text.lower()
    out: list[str] = []
    for kw in FEATURE_LEXICON:
        if kw in low and kw not in out:
            out.append(kw)
    return out


def parse_line(line: str) -> dict | None:
    parts = [p.strip() for p in line.split("|")]
    if len(parts) != 5:
        return None
    rid, topic, intent, sev, sent = parts
    if topic not in TOPICS or intent not in INTENTS or sent not in SENTIMENT_MAP:
        return None
    try:
        sev_i = int(sev)
    except ValueError:
        return None
    if sev_i not in SEVERITY:
        return None
    return {"id": rid, "topic": topic, "intent": intent,
            "severity": sev_i, "sentiment": SENTIMENT_MAP[sent]}


def build_prompt(batch: list[tuple[str, str]]) -> str:
    # Use 1-based line indices (not the long UUID review_id) so the model does not
    # have to echo an id it tends to mangle; code maps index -> review_id by order.
    lines = [f"{j+1}: " + text.replace("\n", " ").strip()[:500]
             for j, (_, text) in enumerate(batch)]
    return PROMPT_HEADER + "\n".join(lines) + "\n"


def load_pending(run_dir: Path) -> list[dict]:
    return [json.loads(l) for l in (run_dir / "pending.jsonl").read_text(
        encoding="utf-8").splitlines() if l.strip()]


def load_rows(csv_path: Path, needed: set[str]) -> dict[str, dict]:
    """Return {review_id: full_row_dict} for the needed ids (all 6 fields)."""
    rows: dict[str, dict] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rid = (row.get("review_id") or "").strip()
            if rid in needed:
                rows[rid] = row
                if len(rows) == len(needed):
                    break
    return rows


def classify(input_csv: str, run_dir: str, provider: str | None,
             limit: int | None, batch_size: int = 50) -> dict:
    load_env()
    rd = Path(run_dir)
    rd.mkdir(parents=True, exist_ok=True)
    csv_path = Path(input_csv)

    pending = load_pending(rd)
    if limit is not None:
        pending = pending[:limit]

    done_path = rd / "_completed.txt"
    completed: set[str] = set()
    if done_path.exists():
        completed = set(done_path.read_text(encoding="utf-8").split())
    phase = "resume" if completed else "initial"

    distinct = [p for p in pending if not p.get("is_dup") and p["review_id"] not in completed]
    dups = [p for p in pending if p.get("is_dup") and p["review_id"] not in completed]

    needed = {p["review_id"] for p in distinct} | {p["review_id"] for p in dups}
    rows = load_rows(csv_path, needed)

    client = make_client(provider, output_token_cap=control("OUTPUT_TOKEN_CAP", 1024))
    model_id = getattr(client, "model", "unknown")
    label_config = make_label_config(model_id, PROMPT_VERSION, SCHEMA_VERSION)

    enriched_fp = (rd / "enriched.jsonl").open("a", encoding="utf-8")
    quar_fp = (rd / "quarantine.jsonl").open("a", encoding="utf-8")
    calls_fp = (rd / "calls.jsonl").open("a", encoding="utf-8")
    done_fp = done_path.open("a", encoding="utf-8")

    stats = {"completed": 0, "quarantined": 0, "dup_reused": 0, "calls": 0,
             "in_tokens": 0, "out_tokens": 0, "retries": 0, "label_config": label_config}
    textsha_to_record: dict[str, dict] = {}
    t0 = time.time()

    def write_record(rec: dict) -> None:
        enriched_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
        done_fp.write(rec["review_id"] + "\n")
        enriched_fp.flush(); done_fp.flush()

    def log_call(ids: list[str], res, outcome: str) -> None:
        calls_fp.write(json.dumps({
            "request_id": uuid.uuid4().hex,
            "role": "enrich",
            "review_ids": ids,
            "model": model_id,
            "phase": phase,
            "outcome": outcome,
            "label_config": label_config,
            "input_tokens": res.input_tokens if res else 0,
            "output_tokens": res.output_tokens if res else 0,
        }, ensure_ascii=False) + "\n")
        calls_fp.flush()

    def run_batch(batch: list[tuple[str, str]]) -> dict[str, dict]:
        prompt = build_prompt(batch)
        ids = [rid for rid, _ in batch]
        try:
            res = client.generate(prompt)
        except ModelError as e:
            log_call(ids, None, "failed")
            print(f"[warn] model error: {e}", file=sys.stderr)
            return {}
        stats["calls"] += 1
        stats["in_tokens"] += res.input_tokens
        stats["out_tokens"] += res.output_tokens
        log_call(ids, res, "succeeded")
        idx_to_rid = {str(j + 1): rid for j, (rid, _) in enumerate(batch)}
        parsed: dict[str, dict] = {}
        for line in res.text.splitlines():
            line = line.strip()
            if "|" in line:
                p = parse_line(line)
                if p and p["id"] in idx_to_rid:
                    parsed[idx_to_rid[p["id"]]] = p
        return parsed

    # ---- distinct texts, in batches ----
    for i in range(0, len(distinct), batch_size):
        chunk = distinct[i:i + batch_size]
        batch = [(p["review_id"], rows[p["review_id"]]["review_text"]) for p in chunk
                 if p["review_id"] in rows]
        parsed = run_batch(batch)
        missing = [b for b in batch if b[0] not in parsed]
        if missing:
            stats["retries"] += 1
            parsed.update(run_batch(missing))

        for rid, text in batch:
            row = rows[rid]
            p = parsed.get(rid)
            if p is None:
                quar_fp.write(json.dumps({
                    "review_id": rid, "status": "quarantined",
                    "reason": "invalid_model_output", "attempts": 2,
                }, ensure_ascii=False) + "\n"); quar_fp.flush()
                stats["quarantined"] += 1
                continue
            rec = completed_record(
                row, topic=p["topic"], intent=p["intent"], sentiment=p["sentiment"],
                severity=p["severity"], entities=extract_entities(text),
                evidence_quote=extract_evidence_quote(text), needs_review=False,
                label_config=label_config)
            errs = validate_completed(rec, row)
            if errs:
                quar_fp.write(json.dumps({
                    "review_id": rid, "status": "quarantined",
                    "reason": "validation:" + ";".join(errs)[:200], "attempts": 2,
                }, ensure_ascii=False) + "\n"); quar_fp.flush()
                stats["quarantined"] += 1
                continue
            write_record(rec)
            textsha_to_record[row_textsha(row)] = rec
            stats["completed"] += 1

        if (i // batch_size) % 10 == 0:
            print(f"  ...{stats['completed']} done, {stats['quarantined']} quar, "
                  f"{stats['calls']} calls, {time.time()-t0:.0f}s", flush=True)

    # ---- duplicates reuse distinct records (no model call) ----
    for p in dups:
        rid = p["review_id"]
        if rid not in rows:
            continue
        row = rows[rid]
        src = textsha_to_record.get(row_textsha(row))
        if src is None:
            continue  # owner not in this slice
        rec = dict(src)
        rec["review_id"] = rid
        rec["source_sha256"] = row_sha(row)
        rec["cache_source_id"] = src["review_id"]
        write_record(rec)
        stats["dup_reused"] += 1

    for fp in (enriched_fp, quar_fp, calls_fp, done_fp):
        fp.close()
    stats["wall_s"] = round(time.time() - t0, 2)
    (rd / "classify_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return stats


def row_textsha(row: dict) -> str:
    from .hashing import text_sha
    return text_sha(row.get("review_text") or "")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 2: classify nonempty reviews.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch-size", type=int, default=50)
    args = ap.parse_args()
    if args.batch_size > 50:
        ap.error("batch-size must be <= 50 (assignment limit)")
    classify(args.input, args.run_dir, args.provider, args.limit, args.batch_size)


if __name__ == "__main__":
    main()
