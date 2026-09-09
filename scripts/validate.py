#!/usr/bin/env python3
"""Strict V6.6 generated-list validator."""
from __future__ import annotations
import re, sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from normalize import normalize_rule
TOTAL_RE = re.compile(r"^! Total rules: ([0-9]+)$")
BUILD_RE = re.compile(r"^! Build-ID: ([0-9a-f]{64})$")
VERSION_RE = re.compile(r"^! Version: v6\.6-[0-9a-f]{12}$")

def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SCRIPT_DIR.parent / "filters.txt"
    if not path.is_file(): print(f"[ERROR] Missing filter file: {path}"); return 1
    seen=set(); errors=[]; previous=None; declared_total=None; build_id=None
    for number, raw in enumerate(path.read_text(encoding="utf-8", errors="strict").splitlines(), 1):
        if m:=TOTAL_RE.match(raw): declared_total=int(m.group(1)); continue
        if m:=BUILD_RE.match(raw): build_id=m.group(1); continue
        if raw.startswith("! Version:") and not VERSION_RE.match(raw): errors.append(f"[VERSION] line {number}: invalid V6.6 version")
        if not raw or raw.lstrip().startswith("!"): continue
        normalized=normalize_rule(raw)
        if normalized is None: errors.append(f"[INVALID] line {number}: {raw[:180]}"); continue
        if normalized in seen: errors.append(f"[DUPLICATE] line {number}: {raw[:180]}")
        seen.add(normalized)
        if previous is not None and raw.casefold() < previous.casefold(): errors.append(f"[UNSORTED] line {number}: {raw[:180]}")
        previous=raw
        if normalized != raw: errors.append(f"[NONCANONICAL] line {number}: {raw[:180]}")
    if declared_total != len(seen): errors.append(f"[COUNT] declared {declared_total}, found {len(seen)} unique rules")
    if not build_id: errors.append("[BUILD-ID] missing or invalid")
    for e in errors[:100]: print(e)
    print(f"Accepted rules: {len(seen)}")
    print(f"Errors:         {len(errors)}")
    return 1 if errors else 0
if __name__ == "__main__": raise SystemExit(main())
