#!/usr/bin/env python3
"""scripts/monitor_memory.py --pid PID --out FILE [--interval 10]

Samples the WHOLE PROCESS TREE (the given PID plus every descendant -- the pipeline process
plus any mediation-bootstrap worker processes it forks) every --interval seconds, appending
one line per sample to --out: "<UTC timestamp> <total_rss_gib>". Runs until the root PID no
longer exists, then exits 0.

Whole-process-tree memory is the number that matters once mediation workers fork (see
calibration_20pct.json gate2_reference_memory_points: Gate 2's 1% run had a 4.05 GiB /usr/bin/
time command-RSS peak but a 13.93 GiB whole-container peak with 8 workers) -- a single-process
RSS reading would badly understate real usage. Uses psutil so this works the same way on
Linux (Workbench) and macOS (this laptop's local test).
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

try:
    import psutil
except ImportError:
    print("ERROR: psutil is not installed in this environment. Run scripts/setup_env.sh first.", file=sys.stderr)
    raise SystemExit(1)


def total_tree_rss_gib(pid: int) -> float | None:
    try:
        root = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return None
    total = 0
    procs = [root] + root.children(recursive=True)
    for proc in procs:
        try:
            total += proc.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total / (1024 ** 3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--out", required=True)
    parser.add_argument("--interval", type=float, default=10.0)
    args = parser.parse_args()

    with open(args.out, "a", encoding="utf-8", newline="\n") as f:
        while True:
            rss_gib = total_tree_rss_gib(args.pid)
            if rss_gib is None:
                print(f"monitor_memory: PID {args.pid} no longer exists; stopping.", file=sys.stderr)
                return 0
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            f.write(f"{ts} {rss_gib:.4f}\n")
            f.flush()
            time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
