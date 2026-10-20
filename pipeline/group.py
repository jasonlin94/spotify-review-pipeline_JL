"""Stage 4 - Group  (membership is CODE-owned; a model only names issues).

Baseline grouping is deterministic: every completed complaint/cancellation record
joins exactly one issue, keyed by its primary `topic`. This satisfies the
contract (each complaint in >=1 issue, no duplicate (issue_id, review_id), no
multi-issue unless declared) and lets ranking regenerate with no model call.

A single `group`-role model call produces human-friendly issue titles from a
bounded set of example quotes (saved to issue_titles.json). Titles are cosmetic;
membership/ranking never depend on them. The call is logged to calls.jsonl so the
required four roles (enrich/verify/group/memo) are all present.

Outputs under <run_dir>/:
  membership.csv      - issue_id,review_id  (one pair per membership)
  issue_titles.json   - issue_id -> short title (from the group model call)

Usage:
  python -m pipeline.group --run-dir data/outputs/full01
"""
from __future__ import annotations

import argparse
import csv
import json
import uuid
from pathlib import Path

from .config import load_env
from .labels import RANKABLE_INTENTS
from .model_client import ModelError, make_client

GROUP_PROMPT_VERSION = "group-v1"


def load_records(run_dir: Path) -> list[dict]:
    recs = []
    p = run_dir / "enriched.jsonl"
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            recs.append(json.loads(line))
    return recs


def group(run_dir: str, provider: str | None = None) -> dict:
    load_env()
    rd = Path(run_dir)
    recs = load_records(rd)

    # Deterministic membership: issue_id = topic, for complaint/cancellation only.
    membership: list[tuple[str, str]] = []
    examples: dict[str, list[str]] = {}
    for r in recs:
        if r.get("status") != "completed":
            continue
        if r["intent"] in RANKABLE_INTENTS:
            iid = r["topic"]
            membership.append((iid, r["review_id"]))
            if len(examples.setdefault(iid, [])) < 5 and r.get("evidence_quote"):
                examples[iid].append(r["evidence_quote"][:120])

    with (rd / "membership.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["issue_id", "review_id"])
        for iid, rid in membership:
            w.writerow([iid, rid])

    # One group-role model call: suggest readable titles from bounded examples.
    titles = {iid: iid for iid in examples}  # fallback = topic name
    client = make_client(provider)
    model_id = getattr(client, "model", "unknown")
    lines = []
    for iid, exs in sorted(examples.items()):
        joined = " | ".join(e.replace("\n", " ") for e in exs)
        lines.append(f"{iid}:: {joined}")
    prompt = ("For each issue code below, give a short (<=6 word) human title "
              "describing the recurring complaint. Output 'code|title' per line, "
              "no extra text.\n\n" + "\n".join(lines) + "\n")
    outcome, in_tok, out_tok = "failed", 0, 0
    try:
        res = client.generate(prompt)
        outcome, in_tok, out_tok = "succeeded", res.input_tokens, res.output_tokens
        for ln in res.text.splitlines():
            if "|" in ln:
                code, _, title = ln.partition("|")
                code, title = code.strip(), title.strip()
                if code in titles and title:
                    titles[code] = title
    except ModelError as e:
        print(f"[warn] group title call failed: {e}")

    with (rd / "calls.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "request_id": uuid.uuid4().hex, "role": "group",
            "review_ids": [], "model": model_id, "phase": "initial",
            "outcome": outcome, "label_config": f"{model_id}+{GROUP_PROMPT_VERSION}+schema-v1",
            "input_tokens": in_tok, "output_tokens": out_tok,
        }, ensure_ascii=False) + "\n")

    (rd / "issue_titles.json").write_text(
        json.dumps(titles, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = {"issues": len(examples), "memberships": len(membership),
               "group_call_outcome": outcome, "titles": titles}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 4: group complaints into issues.")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--provider", default=None)
    args = ap.parse_args()
    group(args.run_dir, args.provider)


if __name__ == "__main__":
    main()
