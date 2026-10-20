"""Required 100-review cost & runtime calculator.

Two commands:
  offline   (DEFAULT) - recompute costs from saved cost/usage.csv + cost/rates.csv
                        and write cost/report.md. NO API key, NO model calls.
  run-pilot (EXPLICIT, paid) - run the full pipeline on cost_100.csv cold (empty
                        cache) then warm (zero new enrichment), saving
                        pilot_records.jsonl, pilot_calls.jsonl, usage.csv.

Arithmetic (per COST_CALCULATOR.md):
  item_cost  = billed_units * price_per_unit     (price_per_1m / 1_000_000)
  total_cost = sum(item_cost)
Cached input is subtracted from input before the uncached rate is applied.

Offline replay is deterministic: with usage fixed, doubling a rate doubles that
API subtotal and leaves measured time + local-compute untouched; changing the
projected record count never changes the measured-100 numbers.

Usage:
  python -m cost.calculator                 # offline replay (default)
  python -m cost.calculator offline --budget 5
  python -m cost.calculator run-pilot       # paid; runs the real 100-review pilot
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import time
from pathlib import Path

COST_DIR = Path(__file__).resolve().parent
DATASET = COST_DIR.parent / "data" / "dataset"
COST_100 = DATASET / "cost_100.csv"
CHECKER = DATASET / "check_submission.py"

# Full-run projection constants (from manifest / contract).
FULL_NONEMPTY = 660_609
FULL_DISTINCT = 484_189


# ----------------------------- offline replay -----------------------------

def read_rates(path: Path) -> dict[tuple[str, str], dict]:
    rates = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rates[(r["model"], r["tier"])] = r
    return rates


def read_usage(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def cost_of(in_tok: int, cached_tok: int, out_tok: int, rate: dict) -> float:
    pin = float(rate["input_per_1m"]) / 1_000_000
    pcache = float(rate["cached_input_per_1m"]) / 1_000_000
    pout = float(rate["output_per_1m"]) / 1_000_000
    uncached_in = max(in_tok - cached_tok, 0)
    return uncached_in * pin + cached_tok * pcache + out_tok * pout


def offline(budget: float, tier: str, fallback_fraction: float,
            output_cap: int, max_workers: int) -> dict:
    rates = read_rates(COST_DIR / "rates.csv")
    usage = read_usage(COST_DIR / "usage.csv")

    # Measured 100-review cost by stage, at the chosen tier.
    by_stage = {}
    measured_in = measured_out = 0
    total_cost = 0.0
    for u in usage:
        model, stage = u["model"], u["stage"]
        in_tok, cached, out_tok = int(u["input_tokens"]), int(u.get("cached_input_tokens", 0) or 0), int(u["output_tokens"])
        rate = rates.get((model, tier)) or rates.get((model, "paid"))
        c = cost_of(in_tok, cached, out_tok, rate)
        by_stage.setdefault(stage, {"input": 0, "output": 0, "cost": 0.0, "model": model})
        by_stage[stage]["input"] += in_tok
        by_stage[stage]["output"] += out_tok
        by_stage[stage]["cost"] += c
        measured_in += in_tok
        measured_out += out_tok
        total_cost += c

    # Enrichment is the stage that scales with review count; others are ~fixed overhead.
    enrich = by_stage.get("enrich", {"input": 0, "output": 0, "cost": 0.0, "model": ""})
    fixed_cost = sum(v["cost"] for k, v in by_stage.items() if k != "enrich")
    # Distinct texts classified in the pilot (enrich input scales per distinct text).
    pilot_distinct = enrich_distinct()
    per_distinct_cost = enrich["cost"] / pilot_distinct if pilot_distinct else 0.0

    def project(distinct: int, retry_mult: float, fb: float) -> float:
        base = per_distinct_cost * distinct * retry_mult
        # capped fallback fraction routed to same model here (cheap); add as multiplier
        return base * (1 + fb) + fixed_cost

    proj = {
        "reuse_base": project(FULL_DISTINCT, 1.0, fallback_fraction),
        "reuse_conservative": project(FULL_DISTINCT, 1.15, fallback_fraction),
        "no_reuse_base": project(FULL_NONEMPTY, 1.0, fallback_fraction),
        "no_reuse_conservative": project(FULL_NONEMPTY, 1.15, fallback_fraction),
    }

    meta = json.loads((COST_DIR / "pilot_meta.json").read_text(encoding="utf-8")) \
        if (COST_DIR / "pilot_meta.json").exists() else {}

    result = {
        "tier": tier,
        "measured_100": {
            "input_tokens": measured_in, "output_tokens": measured_out,
            "api_cost": round(total_cost, 6),
            "cold_wall_s": meta.get("cold_wall_s"),
            "warm_wall_s": meta.get("warm_wall_s"),
            "warm_new_enrich_calls": meta.get("warm_new_enrich_calls"),
            "completed": meta.get("completed"), "failed": meta.get("failed"),
            "cost_per_1000_inputs": round(total_cost / (meta.get("pilot_rows", 100) / 1000), 6),
            "cost_per_completed_record": round(total_cost / meta["completed"], 8)
            if meta.get("completed") else None,
            "by_stage": {k: {"input": v["input"], "output": v["output"],
                             "cost": round(v["cost"], 8), "model": v["model"]}
                         for k, v in by_stage.items()},
        },
        "controls": {"budget_usd": budget, "output_token_cap": output_cap,
                     "max_workers": max_workers, "fallback_fraction": fallback_fraction},
        "full_run_projection": {k: round(v, 4) for k, v in proj.items()},
        "over_budget": {k: (v > budget) for k, v in proj.items()},
        "note": "API spend shown at tier='%s'. Free tier = $0 actual (rate/day limited). "
                "Local-compute (your machine running the orchestrator) is not an API "
                "charge and is listed separately in report.md." % tier,
    }
    write_report(result, rates, tier)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if any(result["over_budget"].values()):
        print("\n[BUDGET WARNING] a projected scenario exceeds the declared budget "
              f"${budget}; see full_run_projection.")
    return result


def enrich_distinct() -> int:
    meta = COST_DIR / "pilot_meta.json"
    if meta.exists():
        return json.loads(meta.read_text(encoding="utf-8")).get("enrich_distinct", 100)
    return 100


def write_report(result: dict, rates: dict, tier: str) -> None:
    m = result["measured_100"]
    lines = [
        "# Cost & Runtime Report — 100-review pilot", "",
        f"_Offline replay. API tier shown: **{tier}**. Recompute anytime with_ "
        "`python -m cost.calculator offline`.", "",
        "## Measured on cost_100.csv (facts)", "",
        f"- Input tokens: **{m['input_tokens']}**, output tokens: **{m['output_tokens']}**",
        f"- Completed: **{m['completed']}**, failed: **{m['failed']}**",
        f"- Cold wall-clock: **{m['cold_wall_s']} s**; warm wall-clock: **{m['warm_wall_s']} s**",
        f"- Warm run new enrichment calls: **{m['warm_new_enrich_calls']}** (cache reuse)",
        f"- API cost @ {tier}: **${m['api_cost']}**  "
        f"(free tier actual = $0; paid shown for projection)",
        f"- Cost per 1,000 input rows: ${m['cost_per_1000_inputs']}; "
        f"per completed record: ${m['cost_per_completed_record']}", "",
        "### By stage", "",
        "| stage | model | input tok | output tok | cost |", "|---|---|---|---|---|",
    ]
    for k, v in m["by_stage"].items():
        lines.append(f"| {k} | {v['model']} | {v['input']} | {v['output']} | ${v['cost']} |")
    p = result["full_run_projection"]
    c = result["controls"]
    lines += [
        "", "## Full-run projection (estimate)", "",
        f"Scaling the enrichment stage by distinct texts; fixed overhead (verify/group/memo) "
        f"added once. Budget ${c['budget_usd']}, fallback fraction {c['fallback_fraction']}.", "",
        "| scenario | distinct/nonempty | projected API cost | over budget? |",
        "|---|---|---|---|",
        f"| exact-text reuse, base | {FULL_DISTINCT:,} | ${p['reuse_base']} | {result['over_budget']['reuse_base']} |",
        f"| exact-text reuse, conservative (+15% retries) | {FULL_DISTINCT:,} | ${p['reuse_conservative']} | {result['over_budget']['reuse_conservative']} |",
        f"| NO reuse, base | {FULL_NONEMPTY:,} | ${p['no_reuse_base']} | {result['over_budget']['no_reuse_base']} |",
        f"| NO reuse, conservative | {FULL_NONEMPTY:,} | ${p['no_reuse_conservative']} | {result['over_budget']['no_reuse_conservative']} |",
        "", "## Controls", "",
        f"- Editable budget: ${c['budget_usd']}", f"- Output-token cap: {c['output_token_cap']}",
        f"- Max workers: {c['max_workers']}", f"- Max fallback fraction: {c['fallback_fraction']}",
        "", "## Local compute (not an API charge)", "",
        "The orchestrator runs on the student's machine (Windows, Intel Arc iGPU). "
        "No GPU inference is used locally for the Gemini path; local cost is wall-clock "
        "time + electricity only and is not billed by the provider.", "",
        "## Rates used (editable; see rates.csv)", "",
        "| model | tier | in/1M | cached/1M | out/1M | source | checked |",
        "|---|---|---|---|---|---|---|",
    ]
    for (model, t), r in rates.items():
        lines.append(f"| {model} | {t} | {r['input_per_1m']} | {r['cached_input_per_1m']} | "
                     f"{r['output_per_1m']} | {r['source_url']} | {r['checked_date']} |")
    (COST_DIR / "report.md").write_text("\n".join(lines), encoding="utf-8")


# ----------------------------- paid pilot -----------------------------

def run_pilot(provider: str | None) -> None:
    from pipeline import classify as C
    from pipeline import export_grading as E
    from pipeline import group as G
    from pipeline import memo as MM
    from pipeline import prepare as P
    from pipeline import rank as R
    from pipeline import verify as V

    run = COST_DIR.parent / "data" / "outputs" / "cost_pilot"
    if run.exists():
        shutil.rmtree(run)  # empty result cache for this experiment
    run.mkdir(parents=True)

    P.prepare(str(COST_100), "cost_pilot",
              out_root=str(COST_DIR.parent / "data" / "outputs"))

    t = time.time()
    cstats = C.classify(str(COST_100), str(run), provider, None)
    V.verify(str(run), str(COST_100), sample=20, seed="verify-v1", provider=provider)
    G.group(str(run), provider)
    R.rank(str(run))
    grad = run / "grading"
    E.export(str(run), str(COST_100), str(COST_100), str(CHECKER), str(grad))
    MM.memo(str(grad), str(run), str(run / "memo.md"), provider)
    cold_wall = round(time.time() - t, 2)

    # WARM run: classify again -> zero new enrichment calls under unchanged settings.
    tw = time.time()
    wstats = C.classify(str(COST_100), str(run), provider, None)
    warm_wall = round(time.time() - tw, 2)

    # Assemble cost/ evidence.
    shutil.copy(run / "enriched.jsonl", COST_DIR / "pilot_records.jsonl")
    shutil.copy(run / "calls.jsonl", COST_DIR / "pilot_calls.jsonl")

    # usage.csv: per-stage token totals from calls.jsonl.
    by = {}
    for line in (run / "calls.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("outcome") != "succeeded":
            continue
        key = (e["model"], e["role"])
        b = by.setdefault(key, {"input": 0, "output": 0})
        b["input"] += e.get("input_tokens", 0)
        b["output"] += e.get("output_tokens", 0)
    with (COST_DIR / "usage.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stage", "model", "input_tokens", "cached_input_tokens", "output_tokens"])
        for (model, role), b in by.items():
            w.writerow([role, model, b["input"], 0, b["output"]])

    meta = {
        "pilot_rows": 100, "enrich_distinct": cstats["completed"],
        "completed": cstats["completed"] + cstats["dup_reused"],
        "failed": cstats["quarantined"],
        "cold_wall_s": cold_wall, "warm_wall_s": warm_wall,
        "warm_new_enrich_calls": wstats["calls"],
    }
    (COST_DIR / "pilot_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"cold_wall_s": cold_wall, "warm_wall_s": warm_wall,
                      "warm_new_enrich_calls": wstats["calls"], **meta}, indent=2))
    print("\nPilot evidence saved under cost/. Now run: python -m cost.calculator offline")


def main() -> None:
    ap = argparse.ArgumentParser(description="100-review cost/runtime calculator.")
    sub = ap.add_subparsers(dest="command")
    o = sub.add_parser("offline", help="recompute from saved usage (default; no API)")
    o.add_argument("--budget", type=float, default=5.0)
    o.add_argument("--tier", default="paid", choices=["paid", "free"])
    o.add_argument("--fallback-fraction", type=float, default=0.05)
    o.add_argument("--output-cap", type=int, default=1024)
    o.add_argument("--max-workers", type=int, default=1)
    pp = sub.add_parser("run-pilot", help="EXPLICIT paid run of the 100-review pilot")
    pp.add_argument("--provider", default=None)
    args = ap.parse_args()
    if args.command == "run-pilot":
        run_pilot(args.provider)
    else:  # default = offline
        offline(getattr(args, "budget", 5.0), getattr(args, "tier", "paid"),
                getattr(args, "fallback_fraction", 0.05),
                getattr(args, "output_cap", 1024), getattr(args, "max_workers", 1))


if __name__ == "__main__":
    main()
