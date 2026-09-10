#!/usr/bin/env python3
"""Optional external-engine differential corpus harness."""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "corpus"

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
        proc = subprocess.run(rendered, shell=True, text=True, capture_output=True)
        if proc.returncode == 0:
            print(f"[OK] {fixture.name}")
        else:
            failures += 1
            print(f"[FAIL] {fixture.name}: {proc.stderr.strip() or proc.stdout.strip()}")
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
