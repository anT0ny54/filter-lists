#!/usr/bin/env bash
set -Eeuo pipefail
shopt -s nullglob

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

SOURCES="$REPO_DIR/sources.txt"
OUTPUT="$REPO_DIR/filters.txt"

DOWNLOAD_TIMEOUT=90
INCLUDE_TIMEOUT=60
TOTAL_TIMEOUT=3300
MAX_INCLUDE_DEPTH=3
CURL_RETRIES=2

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

START_TIME=$(date +%s)
DOWNLOADED="$TMP_DIR/downloaded.urls"
: > "$DOWNLOADED"

log() {
    printf '%s\n' "$*"
}

timed_out() {
    (( "$(date +%s)" - START_TIME >= TOTAL_TIMEOUT ))
}

already_downloaded() {
    grep -Fqx -- "$1" "$DOWNLOADED"
}

mark_downloaded() {
    printf '%s\n' "$1" >> "$DOWNLOADED"
}

valid_url() {
    [[ "$1" =~ ^https?://[^[:space:]]+$ ]]
}

validate_filter_list() {
    local file="$1"
    local url="$2"
    local bytes lines mime

    bytes=$(wc -c < "$file")
    lines=$(wc -l < "$file")

    if (( bytes < 500 )); then
        log "   [SKIP] Too small (${bytes} bytes) — $url"
        return 1
    fi

    if (( lines < 5 )); then
        log "   [SKIP] Too few lines (${lines}) — $url"
        return 1
    fi

    if head -30 "$file" | grep -qiE \
        '^[[:space:]]*(<!doctype|<html|<head|<title|HTTP/[0-9.] [45][0-9][0-9])'; then
        log "   [SKIP] HTML/error response — $url"
        return 1
    fi

    if head -5 "$file" | grep -qE '^[[:space:]]*\{'; then
        log "   [SKIP] JSON response — $url"
        return 1
    fi

    mime=$(file -b --mime-type "$file" 2>/dev/null || true)

    case "$mime" in
        application/octet-stream|application/zip|application/gzip|\
        application/x-executable|application/x-dosexec)
            log "   [SKIP] Binary content — $url"
            return 1
            ;;
    esac

    return 0
}

download_list() {
    local url="$1"
    local output="$2"
    local timeout="$3"

    valid_url "$url" || return 1
    already_downloaded "$url" && return 2

    mark_downloaded "$url"

    curl \
        --fail \
        --silent \
        --show-error \
        --location \
        --compressed \
        --retry "$CURL_RETRIES" \
        --retry-delay 2 \
        --connect-timeout 20 \
        --max-time "$timeout" \
        --output "$output" \
        "$url"
}

resolve_url() {
    local base="$1"
    local include="$2"

    if [[ "$include" =~ ^https?:// ]]; then
        printf '%s\n' "$include"
    else
        printf '%s\n' "${base%/*}/$include"
    fi
}

resolve_includes() {
    local file="$1"
    local base_url="$2"
    local depth="$3"

    (( depth >= MAX_INCLUDE_DEPTH )) && return 0
    timed_out && return 0

    local include_path include_url include_file
    local include_index=0

    while IFS= read -r include_path; do
        include_path="${include_path//$'\r'/}"
        [[ -z "$include_path" ]] && continue

        include_url=$(resolve_url "$base_url" "$include_path")
        include_file="$TMP_DIR/include_${depth}_${include_index}.txt"
        include_index=$((include_index + 1))

        if download_list "$include_url" "$include_file" "$INCLUDE_TIMEOUT"; then
            if validate_filter_list "$include_file" "$include_url"; then
                printf '%s\n' "$include_file" >> "$TMP_DIR/files"
                resolve_includes \
                    "$include_file" \
                    "$include_url" \
                    $((depth + 1))
            fi
        fi
    done < <(
        sed -n 's/^[[:space:]]*!#include[[:space:]]\+//p' "$file"
    )
}

[[ -f "$SOURCES" ]] || {
    log "[ERROR] Missing sources file: $SOURCES"
    exit 1
}

SOURCE_COUNT=$(
    grep -cEv '^[[:space:]]*(#|$)' "$SOURCES" || true
)

log ">> Found $SOURCE_COUNT source URLs"
log ">> Downloading filter lists..."
log

: > "$TMP_DIR/files"

total=0
success=0
failed=0
skipped=0
index=0

while IFS= read -r url || [[ -n "$url" ]]; do
    url="${url//$'\r'/}"

    [[ -z "$url" ]] && continue
    [[ "$url" =~ ^[[:space:]]*# ]] && continue

    if timed_out; then
        log "   [!] Total timeout reached"
        break
    fi

    total=$((total + 1))
    file="$TMP_DIR/source_${index}.txt"
    index=$((index + 1))

    case "$(download_list "$url" "$file" "$DOWNLOAD_TIMEOUT"; echo "$?")" in
        0)
            if validate_filter_list "$file" "$url"; then
                lines=$(wc -l < "$file")
                log "   [OK] $lines lines — ${url:0:100}"
                printf '%s\n' "$file" >> "$TMP_DIR/files"
                success=$((success + 1))

                if grep -qE '^[[:space:]]*!#include[[:space:]]+' "$file"; then
                    log "      Resolving includes..."
                    resolve_includes "$file" "$url" 0
                fi
            else
                rm -f "$file"
                skipped=$((skipped + 1))
            fi
            ;;
        2)
            log "   [SKIP] Duplicate source — $url"
            skipped=$((skipped + 1))
            ;;
        *)
            log "   [FAIL] ${url:0:100}"
            rm -f "$file"
            failed=$((failed + 1))
            ;;
    esac
done < "$SOURCES"

log
log ">> Downloaded $success/$total lists"
log ">> $failed failed, $skipped skipped"
log ">> Processing rules..."

python3 - "$TMP_DIR/files" "$OUTPUT" <<'PY'
from __future__ import annotations

import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone

files_file, output_file = sys.argv[1:3]

# Rules that are not suitable for combined ABP/uBO syntax.
UNSUPPORTED_OPTIONS = re.compile(
    r"(?:^|[,|])(?:app|denyallow|method|header)=",
    re.IGNORECASE,
)

INCLUDE_DIRECTIVE = re.compile(r"^\s*!#include\b", re.IGNORECASE)
COMMENT_LINE = re.compile(r"^\s*(?:!|\[Adblock)")
COSMETIC_RULE = re.compile(r"^\s*([^#]*?)(##|#@#)(.*)$")

# These are usually subscription metadata or update-control directives.
SKIP_DIRECTIVES = (
    "! checksum",
    "! expires",
    "! homepage",
    "! license",
    "! title",
    "! version",
    "! last updated",
    "! redirect",
    "! redirect-rule",
    "! moveto",
    "! diff-path",
)

def normalize_domains(value: str) -> str:
    domains = {
        item.strip().lower()
        for item in value.split(",")
        if item.strip()
    }
    return ",".join(sorted(domains))

def normalize_cosmetic(rule: str) -> str:
    match = COSMETIC_RULE.match(rule)
    if not match:
        return rule.strip()

    domains, separator, selector = match.groups()

    domains = normalize_domains(domains)
    selector = re.sub(r"\s+", " ", selector.strip())
    selector = re.sub(r"\s*,\s*", ",", selector)

    return f"{domains}{separator}{selector}" if domains else \
           f"{separator}{selector}"

def normalize_network(rule: str) -> str:
    rule = rule.strip()

    # Remove unnecessary leading/trailing whitespace only.
    # Do not remove spaces inside ABP regular expressions.
    return rule

def canonical(rule: str) -> str:
    if "##" in rule or "#@#" in rule:
        return normalize_cosmetic(rule)

    return normalize_network(rule)

def is_valid_rule(line: str) -> bool:
    if not line:
        return False

    lower = line.lower()

    if INCLUDE_DIRECTIVE.match(line):
        return False

    if lower.startswith(SKIP_DIRECTIVES):
        return False

    if COMMENT_LINE.match(line):
        return False

    if line.startswith(("[", "{", "<")):
        return False

    if "<html" in lower or "<!doctype" in lower:
        return False

    if UNSUPPORTED_OPTIONS.search(line):
        return False

    # Remove known uBO-only JavaScript cosmetic rules.
    if "-abp-properties(" in lower:
        return False

    # Keep only trusted YouTube cosmetic rules if desired.
    if "youtube.com" in lower and "##" in line:
        if "##+js(trusted-" not in lower:
            return False

    return True

files = []
with open(files_file, encoding="utf-8", errors="ignore") as source:
    files = [line.strip() for line in source if line.strip()]

rules: OrderedDict[str, str] = OrderedDict()

for filename in files:
    try:
        with open(filename, encoding="utf-8", errors="ignore") as source:
            for raw in source:
                line = raw.strip()

                if not is_valid_rule(line):
                    continue

                normalized = canonical(line)
                rules.setdefault(normalized, normalized)

    except OSError:
        continue

final_rules = sorted(rules.values(), key=str.casefold)

if not final_rules:
    print("[ERROR] No valid rules collected.", file=sys.stderr)
    raise SystemExit(1)

now = datetime.now(timezone.utc)
version = now.strftime("v%Y.%m.%d.%H%M")
timestamp = now.strftime("%Y-%m-%d %H:%M:%S UTC")

header = [
    "! Title: Combined Adblock Filter List",
    f"! Version: {version}",
    f"! Last updated: {timestamp}",
    "! Expires: 1 day",
    "! Homepage: https://github.com/anT0ny54/filter-lists",
    "! License: https://github.com/SamirPaulb/filter-lists/blob/main/LICENSE",
    f"! Total rules: {len(final_rules)}",
    "!",
    "! Auto-generated. Do not edit directly.",
    "! Edit sources.txt and rebuild.",
    "!",
]

with open(output_file, "w", encoding="utf-8", newline="\n") as output:
    output.write("\n".join(header))
    output.write("\n")
    output.write("\n".join(final_rules))
    output.write("\n")

print(f">> Wrote {len(final_rules)} rules")
PY

elapsed=$(( $(date +%s) - START_TIME ))

log
log ">> Output: $OUTPUT"
log ">> Completed in ${elapsed}s"
log ">> Done!"
