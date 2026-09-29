#!/usr/bin/env python3
"""Optional external-engine differential corpus harness."""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "corpus"
ENGINE_TIMEOUT = 300  # seconds per fixture; a hung engine must not stall CI forever

def main() -> int:
    command = os.environ.get("FILTER_ENGINE_CMD")
    if not command:
        print("SKIP: FILTER_ENGINE_CMD is not configured")
        return 0
    fixtures = sorted(CORPUS.glob("*.txt"))
    if not fixtures:
        print("No corpus fixtures found")
        return 0
    failures = 0
    for fixture in fixtures:
        rendered = command.replace("{input}", shlex.quote(str(fixture)))
        try:
            proc = subprocess.run(rendered, shell=True, text=True, capture_output=True, timeout=ENGINE_TIMEOUT)
        except subprocess.TimeoutExpired:
            failures += 1
            print(f"[FAIL] {fixture.name}: engine timed out after {ENGINE_TIMEOUT}s")
            continue
        if proc.returncode == 0:
            print(f"[OK] {fixture.name}")
        else:
            failures += 1
            print(f"[FAIL] {fixture.name}: {proc.stderr.strip() or proc.stdout.strip()}")
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
