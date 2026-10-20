"""Stage 2 - Classify / Enrich  (model: Gemini flash-lite; batches <= 50).

Consumes pending.jsonl + the source CSV produced/used by Stage 1. For each
DISTINCT nonempty text it asks the model for a compact label line; code fills the
provenance + extraction fields and validates. Duplicate texts reuse the distinct
record (no model call) while keeping their own review_id and cache_source_id.

Model returns ONE line per review:  id|topic|intent|severity|sentiment
Everything else (evidence_quote exact substring, entities, needs_review,
source_sha256, label_config) is produced/validated by code.

Failure policy: invalid/unparseable output is retried ONCE, then the record is
quarantined with a reason + attempt count. Statuses + results are saved
atomically after each batch so an interrupted run resumes without re-paying.

Outputs (under <run_dir>/):
  enriched.jsonl        - one validated record per review_id
  quarantine.jsonl      - appended (empties from Stage 1 + classify failures)
  calls.jsonl           - every model attempt with usage/latency (for cost/)
  _completed.txt        - review_ids already done (resume index)

Usage:
  python -m pipeline.classify --input data/raw/spotify_reviews_18months.csv \
      --run-dir data/outputs/full01 --limit 100000 --provider gemini
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

from .config import control, load_env
from .labels import INTENTS, LABEL_CONFIG_VERSION, SEVERITY, TOPICS
from .model_client import ModelError, make_client
from .schema import new_record, source_sha256, validate_record

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
playback(playback fail/crash/lag) downloads(offline/saved music) \
catalog(content/search/recommendations/lyrics) billing(price/charges/paywall/premium) \
support(support contact/response) other
intent (choose ONE, precedence cancellation>complaint>request>praise>unclear)
severity: integer 1-5 (1 none/praise/feature-request, 2 annoyance, 3 degraded, \
4 core task blocked, 5 serious financial/privacy/data harm)
sentiment: one of -1 -0.5 0 0.5 1
Rules: stars/anger/cancellation alone do not set severity. A paid-plan mention \
alone is not billing. Output ONLY the lines, no header, no extra text.

Reviews:
"""


def extract_evidence_quote(text: str, max_len: int = 160) -> str:
    """Return an EXACT substring of text to use as evidence (always valid)."""
    t = text.strip()
    if len(t) <= max_len:
        return t
    low = text.lower()
    for kw in FEATURE_LEXICON:
        idx = low.find(kw)
        if idx != -1:
            start = max(0, idx - 40)
            return text[start:start + max_len]
    return text[:max_len]


def extract_entities(text: str) -> list[str]:
    low = text.lower()
    found = []
    for kw in FEATURE_LEXICON:
        if kw in low and kw not in found:
            found.append(kw)
    return found


def parse_line(line: str) -> dict | None:
    parts = [p.strip() for p in line.split("|")]
    if len(parts) != 5:
        return None
    rid, topic, intent, sev, sent = parts
    if topic not in TOPICS or intent not in INTENTS:
        return None
    try:
        sev_i = int(sev)
    except ValueError:
        return None
    if sev_i not in SEVERITY:
        return None
    if sent not in SENTIMENT_MAP:
        return None
    return {"id": rid, "topic": topic, "intent": intent,
            "severity": sev_i, "sentiment": SENTIMENT_MAP[sent]}


def build_prompt(batch: list[tuple[str, str]]) -> str:
    lines = [f"{rid}: " + text.replace("\n", " ").strip()[:500]
             for rid, text in batch]
    return PROMPT_HEADER + "\n".join(lines) + "\n"


def load_pending(run_dir: Path) -> list[dict]:
    return [json.loads(l) for l in (run_dir / "pending.jsonl").read_text(
        encoding="utf-8").splitlines() if l.strip()]


def load_id_text_map(csv_path: Path, needed: set[str]) -> dict[str, str]:
    m: dict[str, str] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rid = (row.get("review_id") or "").strip()
            if rid in needed:
                m[rid] = row.get("review_text") or ""
                if len(m) == len(needed):
                    break
    return m


def classify(input_csv: str, run_dir: str, provider: str | None,
             limit: int | None, batch_size: int = 50) -> dict:
    load_env()
    rd = Path(run_dir)
    rd.mkdir(parents=True, exist_ok=True)
    csv_path = Path(input_csv)

    pending = load_pending(rd)
    if limit is not None:
        pending = pending[:limit]

    # Resume: skip ids already completed.
    done_path = rd / "_completed.txt"
    completed: set[str] = set()
    if done_path.exists():
        completed = set(done_path.read_text(encoding="utf-8").split())

    # Distinct texts still needing a model call.
    distinct = [p for p in pending
                if not p.get("is_dup") and p["review_id"] not in completed]
    dups = [p for p in pending if p.get("is_dup")]

    needed_ids = {p["review_id"] for p in distinct}
    id_text = load_id_text_map(csv_path, needed_ids)

    client = make_client(provider,
                         output_token_cap=control("OUTPUT_TOKEN_CAP", 1024))

    enriched_fp = (rd / "enriched.jsonl").open("a", encoding="utf-8")
    quar_fp = (rd / "quarantine.jsonl").open("a", encoding="utf-8")
    calls_fp = (rd / "calls.jsonl").open("a", encoding="utf-8")
    done_fp = done_path.open("a", encoding="utf-8")

    stats = {"completed": 0, "quarantined": 0, "dup_reused": 0,
             "calls": 0, "in_tokens": 0, "out_tokens": 0, "retries": 0}
    sha_to_record: dict[str, dict] = {}
    t_start = time.time()

    def write_record(rec: dict) -> None:
        enriched_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
        done_fp.write(rec["review_id"] + "\n")
        enriched_fp.flush()
        done_fp.flush()

    def classify_batch(batch: list[tuple[str, str]], attempt: int) -> dict[str, dict]:
        prompt = build_prompt(batch)
        t0 = time.time()
        res = client.generate(prompt)
        calls_fp.write(json.dumps({
            "stage": "classify", "prompt_version": PROMPT_VERSION,
            "model": res.model, "batch_size": len(batch), "attempt": attempt,
            "in_tokens": res.input_tokens, "out_tokens": res.output_tokens,
            "latency_s": round(res.latency_s, 3), "ts": time.time(),
        }, ensure_ascii=False) + "\n")
        calls_fp.flush()
        stats["calls"] += 1
        stats["in_tokens"] += res.input_tokens
        stats["out_tokens"] += res.output_tokens
        parsed: dict[str, dict] = {}
        for line in res.text.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            p = parse_line(line)
            if p:
                parsed[p["id"]] = p
        return parsed

    # ---- process distinct texts in batches ----
    for i in range(0, len(distinct), batch_size):
        chunk = distinct[i:i + batch_size]
        batch = [(p["review_id"], id_text.get(p["review_id"], "")) for p in chunk]
        try:
            parsed = classify_batch(batch, attempt=1)
        except ModelError as e:
            parsed = {}
            print(f"[warn] batch model error: {e}", file=sys.stderr)

        missing = [b for b in batch if b[0] not in parsed]
        if missing:  # retry ONCE, just the missing ones
            stats["retries"] += 1
            try:
                parsed.update(classify_batch(missing, attempt=2))
            except ModelError as e:
                print(f"[warn] retry model error: {e}", file=sys.stderr)

        for rid, text in batch:
            p = parsed.get(rid)
            if p is None:
                quar_fp.write(json.dumps({
                    "review_id": rid, "status": "quarantined",
                    "reason": "invalid_model_output", "attempts": 2,
                }, ensure_ascii=False) + "\n")
                quar_fp.flush()
                stats["quarantined"] += 1
                continue
            rec = new_record(
                rid, text, status="completed", topic=p["topic"],
                intent=p["intent"], sentiment=p["sentiment"],
                severity=p["severity"], entities=extract_entities(text),
                evidence_quote=extract_evidence_quote(text),
                needs_review=False,
            )
            errs = validate_record(rec, text, rid)
            if errs:
                rec["needs_review"] = True
                # keep if only soft issues; quarantine on hard schema failure
                hard = [e for e in errs if "substring" not in e]
                if hard:
                    quar_fp.write(json.dumps({
                        "review_id": rid, "status": "quarantined",
                        "reason": "validation:" + ";".join(errs)[:200],
                        "attempts": 2,
                    }, ensure_ascii=False) + "\n")
                    quar_fp.flush()
                    stats["quarantined"] += 1
                    continue
            write_record(rec)
            sha_to_record[rec["source_sha256"]] = rec
            stats["completed"] += 1

        if (i // batch_size) % 10 == 0:
            el = time.time() - t_start
            print(f"  ...{stats['completed']} done, {stats['quarantined']} quarantined, "
                  f"{stats['calls']} calls, {el:.0f}s", flush=True)

    # ---- propagate to duplicate texts (no model call) ----
    for p in dups:
        if p["review_id"] in completed:
            continue
        src = sha_to_record.get(p["source_sha256"])
        if src is None:
            continue  # distinct owner not in this slice; skip
        rid, text = p["review_id"], id_text.get(p["review_id"]) or ""
        rec = dict(src)
        rec["review_id"] = rid
        rec["source_sha256"] = p["source_sha256"]
        rec["cache_source_id"] = p.get("cache_source_id")
        write_record(rec)
        stats["dup_reused"] += 1

    for fp in (enriched_fp, quar_fp, calls_fp, done_fp):
        fp.close()

    stats["wall_s"] = round(time.time() - t_start, 2)
    stats["label_config"] = LABEL_CONFIG_VERSION
    (rd / "classify_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 2: classify nonempty reviews.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--provider", default=None, help="gemini|ollama (default gemini)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch-size", type=int, default=50)
    args = ap.parse_args()
    if args.batch_size > 50:
        ap.error("batch-size must be <= 50 (assignment limit)")
    classify(args.input, args.run_dir, args.provider, args.limit, args.batch_size)


if __name__ == "__main__":
    main()
