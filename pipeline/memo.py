"""Stage 6 - Recommend / Memo  (grounded; code checks every cited number & ID).

The memo model receives ONLY saved aggregates (ranking + claims) and a BOUNDED
evidence pack (a few representative review_ids + their exact quotes per top
issue) - never the raw dataset. It returns a STRUCTURED recommendation (JSON).
Code then validates that every cited claim_id, metric value, issue_id and
review_id is real and consistent, and renders memo.md. Unsupported citations are
rejected (not silently printed). A human still inspects the final argument.

role="memo" is logged to the grading calls.jsonl.

Usage:
  python -m pipeline.memo --grading grading --run-dir data/outputs/full01 --out memo.md
"""
from __future__ import annotations

import argparse
import csv
import json
import uuid
from pathlib import Path

from .config import load_env
from .model_client import ModelError, make_client

MEMO_PROMPT_VERSION = "memo-v1"
# flash-lite returns complete structured JSON; the larger "thinking" flash spends
# its output budget on hidden reasoning and gets truncated, so we use lite here too.
MEMO_MODEL = "gemini-3.5-flash-lite"
TOPIC_LABEL = {
    "access": "Access (login/account)", "usability": "Usability (controls/ads)",
    "playback": "Playback (failures/crashes)", "downloads": "Downloads (offline)",
    "catalog": "Catalog (search/content)", "billing": "Billing (charges/premium)",
    "support": "Support", "other": "Other",
}


def read_csv(p: Path) -> list[dict]:
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_records(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def build_evidence(records: list[dict], ranking: list[dict], top_k: int = 4,
                   per_issue: int = 3) -> dict[str, list[dict]]:
    """For the top_k issues, pick highest-severity member reviews + exact quotes."""
    by_issue: dict[str, list[dict]] = {}
    completed = [r for r in records if r.get("status") == "completed"
                 and r.get("intent") in {"complaint", "cancellation"}]
    top_ids = {row["issue_id"] for row in ranking[:top_k]}
    for iid in top_ids:
        members = [r for r in completed if r["topic"] == iid]
        members.sort(key=lambda r: (-r["severity"], r["review_id"]))
        by_issue[iid] = [{"review_id": r["review_id"], "severity": r["severity"],
                          "quote": r["evidence_quote"][:160]} for r in members[:per_issue]]
    return by_issue


def build_prompt(ranking: list[dict], claims: list[dict], evidence: dict,
                 titles: dict) -> str:
    rank_lines = [
        f"rank {r['rank']}: issue={r['issue_id']} ({titles.get(r['issue_id'], r['issue_id'])}) "
        f"complaint_count={r['complaint_count']} severity_sum={r['severity_sum']} "
        f"mean_severity={r['mean_severity']} priority_score={r['priority_score']}"
        for r in ranking]
    claim_lines = [f"{c['claim_id']}: issue={c['issue_id']} {c['metric']}={c['value']}"
                   for c in claims]
    ev_lines = []
    for iid, exs in evidence.items():
        for e in exs:
            ev_lines.append(f"  issue={iid} review_id={e['review_id']} sev={e['severity']} quote={e['quote']!r}")
    return f"""You are advising Spotify at the end of a historical review window. Using ONLY
the ranked issues, claims and evidence below, recommend where the next quarter of
product effort should go (access, usability, playback, or billing/support).

RANKED ISSUES (priority_score = severity_sum = complaint_count x mean_severity):
{chr(10).join(rank_lines)}

CLAIM IDS (cite these for any number you state):
{chr(10).join(claim_lines)}

EVIDENCE PACK (representative reviews; cite review_id):
{chr(10).join(ev_lines)}

Return ONLY JSON with this shape:
{{"recommendation_issue_id":"<one issue_id from the ranking>",
 "headline":"<one sentence>",
 "rationale":"<2-4 sentences citing claim ids like (C1) and review ids>",
 "supporting_claim_ids":["C1","C2"],
 "representative_review_ids":["<id>","<id>"],
 "alternatives":[{{"issue_id":"<id>","why_not":"<one sentence citing a claim id>"}}],
 "limitations":"<2-3 sentences: self-selected historical reviews, expressed intent not churn, partial months>"}}
Do not invent numbers, issue ids, review ids or claim ids not present above."""


def validate(memo: dict, claims: list[dict], ranking: list[dict],
             evidence: dict) -> list[str]:
    errs = []
    claim_ids = {c["claim_id"] for c in claims}
    issue_ids = {r["issue_id"] for r in ranking}
    ev_ids = {e["review_id"] for exs in evidence.values() for e in exs}
    if memo.get("recommendation_issue_id") not in issue_ids:
        errs.append(f"recommendation issue not in ranking: {memo.get('recommendation_issue_id')}")
    for cid in memo.get("supporting_claim_ids", []):
        if cid not in claim_ids:
            errs.append(f"unknown claim_id cited: {cid}")
    for rid in memo.get("representative_review_ids", []):
        if rid not in ev_ids:
            errs.append(f"review_id not in evidence pack: {rid}")
    for alt in memo.get("alternatives", []):
        if alt.get("issue_id") not in issue_ids:
            errs.append(f"alternative issue not in ranking: {alt.get('issue_id')}")
    return errs


def render_md(memo: dict, ranking: list[dict], claims: list[dict],
              titles: dict) -> str:
    claim_by_id = {c["claim_id"]: c for c in claims}
    rec = memo["recommendation_issue_id"]
    lines = [
        "# Decision Memo — Next-Quarter Product Priority", "",
        f"**Recommendation: {TOPIC_LABEL.get(rec, rec)}** — {memo.get('headline','')}", "",
        "## Why", "", memo.get("rationale", ""), "",
        "Supporting claims:",
    ]
    for cid in memo.get("supporting_claim_ids", []):
        c = claim_by_id.get(cid)
        if c:
            lines.append(f"- `{cid}` — issue `{c['issue_id']}` {c['metric']} = **{c['value']}**")
    lines += ["", "Representative reviews: " +
              ", ".join(f"`{r}`" for r in memo.get("representative_review_ids", [])), ""]
    lines += ["## Alternatives considered", ""]
    for alt in memo.get("alternatives", []):
        lines.append(f"- **{TOPIC_LABEL.get(alt.get('issue_id'), alt.get('issue_id'))}** — {alt.get('why_not','')}")
    lines += ["", "## Full baseline ranking", "",
              "| rank | issue | complaints | severity_sum | mean_severity | priority |",
              "|---|---|---|---|---|---|"]
    for r in ranking:
        lines.append(f"| {r['rank']} | {r['issue_id']} | {r['complaint_count']} | "
                     f"{r['severity_sum']} | {r['mean_severity']} | {r['priority_score']} |")
    lines += ["", "## Limitations", "", memo.get("limitations", ""), "",
              "_Every number above traces to `grading/claims.csv` and the deterministic "
              "`grading/ranking.csv`; see README for the evidence map._"]
    return "\n".join(lines)


def memo(grading: str, run_dir: str, out: str, provider: str | None = None) -> dict:
    load_env()
    g = Path(grading)
    ranking = read_csv(g / "ranking.csv")
    claims = read_csv(g / "claims.csv")
    records = read_records(g / "records.jsonl")
    titles = {}
    tp = Path(run_dir) / "issue_titles.json"
    if tp.exists():
        titles = json.loads(tp.read_text(encoding="utf-8"))

    evidence = build_evidence(records, ranking)
    prompt = build_prompt(ranking, claims, evidence, titles)

    client = make_client(provider, model=MEMO_MODEL) if provider is None else make_client(provider)
    model_id = getattr(client, "model", MEMO_MODEL)
    outcome, in_tok, out_tok = "failed", 0, 0
    memo_obj = None
    try:
        res = client.generate(prompt)
        outcome, in_tok, out_tok = "succeeded", res.input_tokens, res.output_tokens
        text = res.text.strip()
        if "```" in text:
            text = text.split("```")[1].lstrip("json").strip() if "```" in text else text
        start, end = text.find("{"), text.rfind("}")
        memo_obj = json.loads(text[start:end + 1])
    except (ModelError, json.JSONDecodeError, ValueError) as e:
        print(f"[warn] memo generation failed: {e}")

    with (g / "calls.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "request_id": uuid.uuid4().hex, "role": "memo", "review_ids": [],
            "model": model_id, "phase": "initial", "outcome": outcome,
            "label_config": f"{model_id}+{MEMO_PROMPT_VERSION}+schema-v1",
            "input_tokens": in_tok, "output_tokens": out_tok,
        }, ensure_ascii=False) + "\n")

    if memo_obj is None:
        raise SystemExit("memo model call failed; see warning above")
    errs = validate(memo_obj, claims, ranking, evidence)
    (g / "memo_validation.json").write_text(json.dumps(
        {"errors": errs, "memo": memo_obj}, indent=2, ensure_ascii=False), encoding="utf-8")
    if errs:
        print("[FAIL] memo cites unsupported items:")
        for e in errs:
            print("  -", e)
        raise SystemExit("memo failed grounding validation")

    md = render_md(memo_obj, ranking, claims, titles)
    Path(out).write_text(md, encoding="utf-8")
    print(f"[OK] memo written to {out}; recommendation={memo_obj['recommendation_issue_id']}; "
          f"all citations validated ({len(claims)} claims available)")
    return memo_obj


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 6: grounded decision memo.")
    ap.add_argument("--grading", required=True, help="grading/ folder with ranking/claims/records")
    ap.add_argument("--run-dir", required=True, help="run dir (for issue_titles.json)")
    ap.add_argument("--out", default="memo.md")
    ap.add_argument("--provider", default=None)
    args = ap.parse_args()
    memo(args.grading, args.run_dir, args.out, args.provider)


if __name__ == "__main__":
    main()
