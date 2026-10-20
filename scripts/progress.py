"""Show progress of a running (or finished) classification run.

Usage:
  python -m scripts.progress                      # defaults to data/outputs/full01
  python -m scripts.progress --run-dir data/outputs/full01
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

TOTAL_NONEMPTY = 660_609


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default="data/outputs/full01")
    ap.add_argument("--total", type=int, default=TOTAL_NONEMPTY)
    args = ap.parse_args()
    rd = Path(args.run_dir)

    done_file = rd / "_completed.txt"
    completed = sum(1 for _ in done_file.open(encoding="utf-8")) if done_file.exists() else 0
    pct = 100 * completed / args.total

    log = rd.parent / (rd.name + "_run.log")
    last, elapsed, calls, done_this = "", None, None, None
    if log.exists():
        lines = [l for l in log.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
        if lines:
            last = lines[-1]
            # "...<done> done, <quar> quar, <calls> calls, <elapsed>s" (current process)
            m = re.search(r"(\d+) done,.*?(\d+) calls, (\d+)s", last)
            if m:
                done_this, calls, elapsed = int(m.group(1)), int(m.group(2)), int(m.group(3))

    print(f"Run: {rd}")
    print(f"Completed: {completed:,} / {args.total:,}  ({pct:.1f}%)")
    # Rate from THIS process's own completed/elapsed (not cumulative) for a true ETA.
    if elapsed and done_this:
        rate = done_this / elapsed
        remaining = (args.total - completed) / rate if rate else 0
        print(f"Rate: {rate:.1f} reviews/s | ETA ~{remaining/3600:.1f} h "
              f"(this session: {done_this:,} in {elapsed/60:.0f} min)")
    # "finished" only when (near) full coverage; a leftover stats file from an
    # earlier limited run must not be mistaken for completion.
    if completed >= args.total - 50:
        print("STATUS: finished (full coverage reached).")
    else:
        print("STATUS: running.")
    if last:
        print("last log:", last)


if __name__ == "__main__":
    main()
