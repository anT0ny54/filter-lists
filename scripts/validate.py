#!/usr/bin/env python3
"""Strict generated-list validator."""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
from config import load_config  # noqa: E402
from normalize import normalize_rule  # noqa: E402
from report import BUILDER_VERSION  # noqa: E402

TOTAL_RE = re.compile(r"^! Total rules: ([0-9]+)$")
BUILD_RE = re.compile(r"^! Build-ID: ([0-9a-f]{64})$")
SOURCE_MANIFEST_RE = re.compile(r"^! Source manifest SHA-256: ([0-9a-f]{64})$")
VERSION_RE = re.compile(r"^! Version: v" + re.escape(BUILDER_VERSION) + r"-[0-9a-f]{12}$")


def config_fingerprint(config) -> str:
    h = hashlib.sha256()
    for source in config.sources:
        h.update(f"{source.name}\0{source.url}\0{source.category}\0{source.priority}\0{source.required}\n".encode())
    for path in (ROOT / "policies.yaml", ROOT / "custom-rules.txt"):
        if path.exists():
            h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "filters.txt"
    if not path.is_file():
        print(f"[ERROR] Missing filter file: {path}")
        return 1
    try:
        config = load_config()
    except Exception as exc:
        print(f"[ERROR] Configuration: {exc}")
        return 1

    seen: set[str] = set()
    canonical_rules: list[str] = []
    errors: list[str] = []
    declared_total = None
    declared_build_id = None
    declared_source_manifest = None
    version_ok = False

    for number, raw in enumerate(path.read_text(encoding="utf-8", errors="strict").splitlines(), 1):
        if m := TOTAL_RE.match(raw):
            declared_total = int(m.group(1))
            continue
        if m := BUILD_RE.match(raw):
            declared_build_id = m.group(1)
            continue
        if m := SOURCE_MANIFEST_RE.match(raw):
            declared_source_manifest = m.group(1)
            continue
        if raw.startswith("! Version:"):
            version_ok = bool(VERSION_RE.match(raw))
            if not version_ok:
                errors.append(f"[VERSION] line {number}: invalid V7 version")
        if not raw or raw.lstrip().startswith("!"):
            continue

        normalized = normalize_rule(raw, max_rule_length=config.max_rule_length)
        if normalized is None:
            errors.append(f"[INVALID] line {number}: {raw[:180]}")
            continue
        if normalized in seen:
            errors.append(f"[DUPLICATE] line {number}: {raw[:180]}")
        seen.add(normalized)
        canonical_rules.append(normalized)
        if len(canonical_rules) > 1 and canonical_rules[-1].casefold() < canonical_rules[-2].casefold():
            errors.append(f"[UNSORTED] line {number}: {raw[:180]}")
        if normalized != raw:
            errors.append(f"[NONCANONICAL] line {number}: {raw[:180]}")

    if declared_total != len(seen):
        errors.append(f"[COUNT] declared {declared_total}, found {len(seen)} unique rules")
    if declared_build_id is None:
        errors.append("[BUILD-ID] missing or invalid")
    else:
        actual_id = hashlib.sha256((config_fingerprint(config) + "\n" + "\n".join(sorted(seen, key=lambda x: (x.casefold(), x)))).encode()).hexdigest()
        if actual_id != declared_build_id:
            errors.append("[BUILD-ID] does not match configuration and normalized rules")
    if declared_source_manifest is None:
        errors.append("[PROVENANCE] source manifest SHA-256 missing or invalid")
    else:
        manifest = hashlib.sha256()
        for source in config.sources:
            manifest.update(f"{source.name}\0{source.url}\0{source.category}\0{source.priority}\0{source.required}\n".encode())
        if manifest.hexdigest() != declared_source_manifest:
            errors.append("[PROVENANCE] source manifest hash does not match sources.yaml")
    if not version_ok:
        errors.append("[VERSION] missing or invalid")

    for error in errors[:100]:
        print(error)
    print(f"Accepted rules: {len(seen)}")
    print(f"Errors:         {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
