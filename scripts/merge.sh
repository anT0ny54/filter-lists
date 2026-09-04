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

START_TIME="$(date +%s)"
DOWNLOADED="$TMP_DIR/downloaded.urls"
FILES="$TMP_DIR/files"

: > "$DOWNLOADED"
: > "$FILES"

log() {
    printf '%s\n' "$*"
}

timed_out() {
    (( "$(date +%s)" - START_TIME >= TOTAL_TIMEOUT ))
}

valid_url() {
    [[ "$1" =~ ^https?://[^[:space:]]+$ ]]
}

already_downloaded() {
    grep -Fqx -- "$1" "$DOWNLOADED"
}

mark_downloaded() {
    printf '%s\n' "$1" >> "$DOWNLOADED"
}

trim() {
    local value="$1"

    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"

    printf '%s' "$value"
}

validate_filter_list() {
    local file="$1"
    local url="$2"
    local bytes
    local lines
    local mime

    bytes="$(wc -c < "$file")"
    lines="$(wc -l < "$file")"

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

    mime="$(file -b --mime-type "$file" 2>/dev/null || true)"

    case "$mime" in
        application/octet-stream|\
        application/zip|\
        application/gzip|\
        application/x-gzip|\
        application/x-bzip2|\
        application/x-7z-compressed|\
        application/x-rar|\
        application/x-executable|\
        application/x-dosexec)
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

    if already_downloaded "$url"; then
        return 2
    fi

    if curl \
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
        "$url"; then

        mark_downloaded "$url"
        return 0
    fi

    rm -f "$output"
    return 1
}

resolve_url() {
    local base_url="$1"
    local include_path="$2"

    python3 - "$base_url" "$include_path" <<'PY'
from urllib.parse import urljoin
import sys

print(urljoin(sys.argv[1], sys.argv[2]))
PY
}

resolve_includes() {
    local file="$1"
    local base_url="$2"
    local depth="$3"

    (( depth >= MAX_INCLUDE_DEPTH )) && return 0
    timed_out && return 0

    local include_path
    local include_url
    local include_file

    while IFS= read -r include_path; do
        include_path="${include_path//$'\r'/}"
        include_path="$(trim "$include_path")"

        [[ -z "$include_path" ]] && continue

        include_url="$(resolve_url "$base_url" "$include_path")"
        include_file="$(mktemp "$TMP_DIR/include.XXXXXX.txt")"

        if download_list "$include_url" "$include_file" "$INCLUDE_TIMEOUT"; then
            if validate_filter_list "$include_file" "$include_url"; then
                printf '%s\n' "$include_file" >> "$FILES"

                resolve_includes \
                    "$include_file" \
                    "$include_url" \
                    $((depth + 1))
            else
                rm -f "$include_file"
            fi
        else
            rm -f "$include_file"
        fi
    done < <(
        sed -n \
            -E 's/^[[:space:]]*!#include[[:space:]]+(.+)$/\1/p' \
            "$file"
    )
}

[[ -f "$SOURCES" ]] || {
    log "[ERROR] Missing sources file: $SOURCES"
    exit 1
}

SOURCE_COUNT="$(
    grep -cEv '^[[:space:]]*(#|$)' "$SOURCES" || true
)"

log ">> Found $SOURCE_COUNT source URLs"
log ">> Downloading filter lists..."
log

total=0
success=0
failed=0
skipped=0
index=0

while IFS= read -r url || [[ -n "$url" ]]; do
    url="${url//$'\r'/}"
    url="$(trim "$url")"

    [[ -z "$url" ]] && continue
    [[ "$url" =~ ^# ]] && continue

    if timed_out; then
        log "   [!] Total timeout reached"
        break
    fi

    total=$((total + 1))

    file="$TMP_DIR/source_${index}.txt"
    index=$((index + 1))

    if download_list "$url" "$file" "$DOWNLOAD_TIMEOUT"; then
        if validate_filter_list "$file" "$url"; then
            lines="$(wc -l < "$file")"

            log "   [OK] $lines lines — ${url:0:100}"

            printf '%s\n' "$file" >> "$FILES"
            success=$((success + 1))

            if grep -qE \
                '^[[:space:]]*!#include[[:space:]]+' \
                "$file"; then

                log "      Resolving includes..."
                resolve_includes "$file" "$url" 0
            fi
        else
            rm -f "$file"
            skipped=$((skipped + 1))
        fi

    elif already_downloaded "$url"; then
        log "   [SKIP] Duplicate source — $url"
        skipped=$((skipped + 1))

    else
        log "   [FAIL] ${url:0:100}"
        failed=$((failed + 1))
    fi

done < "$SOURCES"

log
log ">> Downloaded $success/$total lists"
log ">> $failed failed, $skipped skipped"
log ">> Processing strict ABP-only rules..."

python3 - "$FILES" "$OUTPUT" <<'PY'
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone

files_file, output_file = sys.argv[1:3]

ALLOWED_OPTIONS = {
    "3p",
    "all",
    "background",
    "badfilter",
    "beacon",
    "collapse",
    "document",
    "elemhide",
    "font",
    "genericblock",
    "generichide",
    "ghide",
    "image",
    "important",
    "jsinject",
    "match-case",
    "media",
    "object",
    "object-subrequest",
    "other",
    "ping",
    "popup",
    "script",
    "sitekey",
    "specifichide",
    "stylesheet",
    "subdocument",
    "third-party",
    "webrtc",
    "websocket",
    "xmlhttprequest",
}

INCLUDE_DIRECTIVE = re.compile(
    r"^\s*!#(?:include|if|endif|else)\b",
    re.IGNORECASE,
)

COMMENT_LINE = re.compile(
    r"^\s*(?:!|\[Adblock(?:\s+Plus)?\b)",
    re.IGNORECASE,
)

COSMETIC_RULE = re.compile(
    r"^(?P<domains>[^#\s,]+(?:,[^#\s,]+)*)?"
    r"(?P<separator>##|#@#)"
    r"(?P<selector>\S.*)$"
)

DOMAIN_TOKEN = re.compile(
    r"^(?:~)?"
    r"(?:[A-Za-z0-9*_-]+\.)*"
    r"[A-Za-z0-9*_-]+$"
)

NETWORK_OPTION_NAME = re.compile(
    r"^[a-z][a-z0-9-]*$",
    re.IGNORECASE,
)

HOSTS_FILE_LINE = re.compile(
    r"^(?:0\.0\.0\.0|127\.0\.0\.1|::1)(?:\s+|$)"
)

UNSUPPORTED_COSMETIC = re.compile(
    r"""
    \#\#\+js\b
    | \#@\#\+js\b
    | \#\?\#
    | \#\$\#
    | \#@\#\$\#
    | \#\#\^
    | \#@\#\^
    | :has-text\s*\(
    | :matches-css(?:-before|-after)?\s*\(
    | :xpath\s*\(
    | :contains\s*\(
    | :style\s*\(
    | :remove\s*\(
    | :watch-attr\s*\(
    | :matches-path\s*\(
    | -abp-properties\s*\(
    | :-abp-
    """,
    re.IGNORECASE | re.VERBOSE,
)


def split_network_options(rule: str) -> tuple[str, list[str]]:
    """
    Keep a complete regular-expression filter intact.
    A '$' inside a complete regex is not an option separator.
    """
    if rule.startswith("/") and rule.endswith("/"):
        return rule, []

    if "$" not in rule:
        return rule, []

    pattern, option_text = rule.rsplit("$", 1)

    if not pattern:
        return rule, []

    options = [
        item.strip().lower()
        for item in option_text.split(",")
        if item.strip()
    ]

    return pattern, options


def valid_domain_list(value: str) -> bool:
    if not value:
        return False

    for domain in value.split("|"):
        domain = domain.strip()

        if not domain:
            return False

        if domain.startswith("~"):
            domain = domain[1:]

        if not DOMAIN_TOKEN.fullmatch(domain):
            return False

    return True


def valid_sitekey(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"[A-Za-z0-9+/=_-]+(?:\|[A-Za-z0-9+/=_-]+)*",
            value,
        )
    )


def valid_network_options(options: list[str]) -> bool:
    seen: set[str] = set()

    for option in options:
        if not option:
            return False

        if "=" in option:
            name, value = option.split("=", 1)
            name = name.strip().lower()
            value = value.strip()

            if name not in {"domain", "sitekey"}:
                return False

            if not NETWORK_OPTION_NAME.fullmatch(name):
                return False

            if not value:
                return False

            if name == "domain" and not valid_domain_list(value):
                return False

            if name == "sitekey" and not valid_sitekey(value):
                return False

        else:
            name = option.lstrip("~").lower()

            if not NETWORK_OPTION_NAME.fullmatch(name):
                return False

            if name not in ALLOWED_OPTIONS:
                return False

        if option in seen:
            return False

        seen.add(option)

    return True


def normalize_domains(value: str) -> str:
    domains = {
        item.strip().lower()
        for item in value.split(",")
        if item.strip()
    }

    return ",".join(sorted(domains))


def normalize_cosmetic(rule: str) -> str | None:
    match = COSMETIC_RULE.fullmatch(rule)

    if not match:
        return None

    domains = match.group("domains")
    separator = match.group("separator")
    selector = match.group("selector").strip()

    if not selector:
        return None

    if domains:
        for domain in domains.split(","):
            if not DOMAIN_TOKEN.fullmatch(domain):
                return None

        domains = normalize_domains(domains)
    else:
        domains = ""

    selector = re.sub(r"\s*,\s*", ",", selector)

    if domains:
        return f"{domains}{separator}{selector}"

    return f"{separator}{selector}"


def normalize_network(rule: str) -> str | None:
    pattern, options = split_network_options(rule)

    if not pattern:
        return None

    if any(character.isspace() for character in pattern):
        return None

    if pattern.startswith("/") and not pattern.endswith("/"):
        return None

    if not valid_network_options(options):
        return None

    if options:
        return f"{pattern}${','.join(options)}"

    return pattern


def is_cosmetic_rule(line: str) -> bool:
    return "##" in line or "#@#" in line


def is_valid_rule(line: str) -> bool:
    line = line.strip()

    if not line or len(line) > 100_000:
        return False

    if COMMENT_LINE.match(line):
        return False

    if INCLUDE_DIRECTIVE.match(line):
        return False

    if line.startswith(("[", "{", "<")):
        return False

    if HOSTS_FILE_LINE.match(line):
        return False

    if "<html" in line.lower() or "<!doctype" in line.lower():
        return False

    if UNSUPPORTED_COSMETIC.search(line):
        return False

    if is_cosmetic_rule(line):
        return normalize_cosmetic(line) is not None

    if "#$" in line or "#?" in line:
        return False

    return normalize_network(line) is not None


def normalize_rule(line: str) -> str | None:
    line = line.strip()

    if is_cosmetic_rule(line):
        return normalize_cosmetic(line)

    return normalize_network(line)


files: list[str] = []

try:
    with open(files_file, encoding="utf-8", errors="ignore") as source:
        files = [
            line.strip()
            for line in source
            if line.strip()
        ]
except OSError:
    files = []


unique_rules: set[str] = set()
accepted = 0
rejected = 0

for filename in files:
    try:
        with open(filename, encoding="utf-8", errors="ignore") as source:
            for raw in source:
                line = raw.rstrip("\r\n")

                if not is_valid_rule(line):
                    rejected += 1
                    continue

                normalized = normalize_rule(line)

                if normalized is None:
                    rejected += 1
                    continue

                unique_rules.add(normalized)
                accepted += 1

    except OSError:
        continue


if not unique_rules:
    print(
        "[ERROR] No strict ABP-compatible rules collected.",
        file=sys.stderr,
    )
    raise SystemExit(1)


final_rules = sorted(unique_rules, key=str.casefold)

now = datetime.now(timezone.utc)
version = now.strftime("v%Y.%m.%d.%H%M")
timestamp = now.strftime("%Y-%m-%d %H:%M:%S UTC")

header = [
    "! Title: Combined Adblock Plus Filter List",
    f"! Version: {version}",
    f"! Last updated: {timestamp}",
    "! Expires: 1 day",
    "! Homepage: https://github.com/anT0ny54/filter-lists",
    "! License: https://github.com/anT0ny54/filter-lists/blob/main/LICENSE",
    f"! Total rules: {len(final_rules)}",
    "!",
    "! Format: Strict Adblock Plus-compatible syntax",
    "! Auto-generated. Do not edit directly.",
    "! Edit sources.txt and rebuild.",
    "!",
]

temporary_output = f"{output_file}.tmp"

try:
    with open(
        temporary_output,
        "w",
        encoding="utf-8",
        newline="\n",
    ) as output:
        output.write("\n".join(header))
        output.write("\n")
        output.write("\n".join(final_rules))
        output.write("\n")

    os.replace(temporary_output, output_file)

except OSError:
    try:
        os.unlink(temporary_output)
    except OSError:
        pass
    raise


print(f">> Accepted rule lines: {accepted}")
print(f">> Rejected rule lines: {rejected}")
print(f">> Unique ABP rules: {len(final_rules)}")
PY

elapsed=$(( "$(date +%s)" - START_TIME ))

log
log ">> Output: $OUTPUT"
log ">> Completed in ${elapsed}s"
log ">> Done!"
