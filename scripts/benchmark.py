#!/usr/bin/env python3
"""Small repeatable normalization + merge benchmark using only the stdlib.

Two phases of the real pipeline are measured:
  1. per-line normalization (`normalize_rule`)
  2. a representative merge workload: normalize -> deduplicate -> deterministic
     (casefold, rule) ordering, mirroring what merge.py does after
     normalization, so a merge-pipeline regression cannot pass CI while only
     normalization is measured.
"""
from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from normalize import normalize_rule, rule_sort_key  # noqa: E402

DEFAULT_INPUT = SCRIPT_DIR.parent / "tests" / "fixtures" / "sample-filter.txt"


def run(lines: list[str], repeats: int) -> tuple[float, int]:
    timings = []; accepted = 0
    for _ in range(repeats):
        start = time.perf_counter(); count = 0
        for line in lines:
            if normalize_rule(line) is not None:
                count += 1
        timings.append(time.perf_counter() - start); accepted = count
    return statistics.median(timings), accepted


def run_merge(lines: list[str], repeats: int) -> tuple[float, int]:
    """Representative merge-pipeline workload: normalize, deduplicate, sort."""
    timings = []; unique = 0
    for _ in range(repeats):
        start = time.perf_counter()
        seen: set[str] = set()
        for line in lines:
            normalized = normalize_rule(line)
            if normalized is not None:
                seen.add(normalized)
        ordered = sorted(seen, key=rule_sort_key)
        timings.append(time.perf_counter() - start)
        unique = len(ordered)
    return statistics.median(timings), unique


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--repeats", type=int, default=5)
    # The shipped fixture is only a handful of lines, which made the reported
    # lines/second meaningless timer noise. Repeat it to get a stable workload.
    parser.add_argument("--multiplier", type=int, default=5000, help="repeat the input N times (default: 5000)")
    parser.add_argument("--skip-merge", action="store_true", help="only run the normalization benchmark")
    args = parser.parse_args()
    lines = args.input.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise SystemExit("benchmark input is empty")
    lines = lines * max(1, args.multiplier)
    median, accepted = run(lines, max(1, args.repeats))
    rate = len(lines) / median if median else float("inf")
    print(f"[normalize] input_lines={len(lines)} accepted={accepted} median_seconds={median:.6f} lines_per_second={rate:.1f}")
    if not args.skip_merge:
        merge_median, unique = run_merge(lines, max(1, args.repeats))
        merge_rate = len(lines) / merge_median if merge_median else float("inf")
        print(f"[merge]     input_lines={len(lines)} unique_rules={unique} median_seconds={merge_median:.6f} lines_per_second={merge_rate:.1f}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
