#!/usr/bin/env python3
"""Small repeatable normalization/merge benchmark using only the stdlib."""
from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from normalize import normalize_rule  # noqa: E402

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--repeats", type=int, default=5)
    # The shipped fixture is only a handful of lines, which made the reported
    # lines/second meaningless timer noise. Repeat it to get a stable workload.
    parser.add_argument("--multiplier", type=int, default=5000, help="repeat the input N times (default: 5000)")
    args = parser.parse_args()
    lines = args.input.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise SystemExit("benchmark input is empty")
    lines = lines * max(1, args.multiplier)
    median, accepted = run(lines, max(1, args.repeats))
    rate = len(lines) / median if median else float("inf")
    print(f"input_lines={len(lines)} accepted={accepted} median_seconds={median:.6f} lines_per_second={rate:.1f}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
