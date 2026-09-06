#!/usr/bin/env python3
"""Validate an existing filter file against the strict ABP output profile."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import merge  # noqa: E402

def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else merge.OUTPUT
    if not path.is_file():
        print(f"[ERROR] Missing filter file: {path}")
        return 1

    accepted = rejected = duplicates = 0
    seen: set[str] = set()
    previous = None
    errors = []

    with path.open(encoding="utf-8", errors="strict") as source:
        for number, raw in enumerate(source, 1):
            line = raw.rstrip("\r\n")
            if not line or line.lstrip().startswith("!"):
                continue

            normalized = merge.normalize_rule(line)
            if normalized is None:
                rejected += 1
                errors.append(f"[INVALID] line {number}: {line[:180]}")
                continue

            accepted += 1
            if normalized in seen:
                duplicates += 1
                errors.append(f"[DUPLICATE] line {number}: {line[:180]}")
            seen.add(normalized)

            if previous is not None and line.casefold() < previous.casefold():
                errors.append(f"[UNSORTED] line {number}: {line[:180]}")
            previous = line

            if normalized != line:
                errors.append(f"[NONCANONICAL] line {number}: {line[:180]}")

    for error in errors[:100]:
        print(error)

    print(f"Accepted rules: {accepted}")
    print(f"Unique rules:   {len(seen)}")
    print(f"Duplicates:     {duplicates}")
    print(f"Invalid rules:  {rejected}")
    print(f"Errors:         {len(errors)}")
    return 1 if errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
