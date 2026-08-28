#!/bin/bash
# merge.sh — Downloads all filter lists, resolves !#include directives,
# deduplicates, and merges into a single file.
# Includes safety validation to reject corrupted or non-filter-list downloads.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SOURCES="$REPO_DIR/sources.txt"
OUTPUT="$REPO_DIR/filters.txt"
TEMP_DIR=$(mktemp -d)
INCLUDE_DIR="$TEMP_DIR/includes"
mkdir -p "$INCLUDE_DIR"

trap 'rm -rf "$TEMP_DIR"' EXIT

# ──────────────────────────────────────────────
# Configuration — tune these if builds get slow
# ──────────────────────────────────────────────
DOWNLOAD_TIMEOUT=90       # Per-URL download timeout (seconds)
INCLUDE_TIMEOUT=60        # Per-include download timeout (seconds)
TOTAL_TIMEOUT=3300        # 55 min hard stop (GitHub Actions job is 60 min)

# Track start time
start_time=$(date +%s)

# Counter file for unique filenames (works across subshells)
echo "0" > "$TEMP_DIR/.counter"

# ──────────────────────────────────────────────
# Safety validation for downloaded filter lists
# ──────────────────────────────────────────────
validate_filter_list() {
    local file="$1"
    local url="$2"
    local lines size
    lines=$(wc -l < "$file" | tr -d ' ')
    size=$(wc -c < "$file" | tr -d ' ')

    if [ "$size" -lt 500 ]; then
        echo "   [SKIP] Too small (${size} bytes) — $url"
        return 1
    fi

    if [ "$lines" -lt 5 ]; then
        echo "   [SKIP] Too few lines (${lines}) — $url"
        return 1
    fi

    if head -20 "$file" | grep -qi '<!doctype\|<html\|HTTP Status [0-9]\|<title>'; then
        echo "   [SKIP] HTML/error page — $url"
        return 1
    fi

    if head -3 "$file" | grep -qE '^[[:space:]]*\{'; then
        echo "   [SKIP] JSON response (not a filter list) — $url"
        return 1
    fi

    if file -b --mime "$file" 2>/dev/null | grep -q 'binary\|octet-stream\|executable'; then
        echo "   [SKIP] Binary content — $url"
        return 1
    fi

    return 0
}

resolve_includes() {
    local file="$1"
    local base_url="$2"
    local depth="$3"

    if [ "$depth" -gt 3 ]; then
        return
    fi

    local now
    now=$(date +%s)
    if [ $((now - start_time)) -gt "$TOTAL_TIMEOUT" ]; then
        echo "      [!] Total timeout reached, stopping includes"
        return
    fi

    local dir_url
    dir_url=$(echo "$base_url" | sed 's|/[^/]*$|/|')

    local inc_list="$TEMP_DIR/.inc_paths_${depth}_$RANDOM.txt"

    grep '^!#include ' "$file" 2>/dev/null | sed 's/^!#include //' | tr -d '\r' > "$inc_list" || true

    while IFS= read -r include_path; do
        [ -z "$include_path" ] && continue

        local include_url
        if echo "$include_path" | grep -q '^https\?://'; then
            include_url="$include_path"
        else
            include_url="${dir_url}${include_path}"
        fi

        local fc
        fc=$(cat "$TEMP_DIR/.counter")
        fc=$((fc + 1))
        echo "$fc" > "$TEMP_DIR/.counter"
        local include_file="$INCLUDE_DIR/inc_${fc}.txt"

        if curl -s -L --compressed --max-time "$INCLUDE_TIMEOUT" --retry 1 \
               -o "$include_file" "$include_url" 2>/dev/null; then
            local inc_lines inc_size
            inc_lines=$(wc -l < "$include_file" | tr -d ' ')
            inc_size=$(wc -c < "$include_file" | tr -d ' ')
            if [ "$inc_lines" -gt 1 ] && [ "$inc_size" -gt 200 ]; then
                if ! head -10 "$include_file" | grep -qi '<!doctype\|<html\|HTTP Status\|<title>'; then
                    echo "      [+] $inc_lines lines — ${include_path:0:60}"
                    resolve_includes "$include_file" "$include_url" $((depth + 1))
                else
                    echo "      [-] HTML/error response — ${include_path:0:60}"
                    rm -f "$include_file"
                fi
            else
                rm -f "$include_file"
            fi
        else
            echo "      [-] Failed/timeout — ${include_path:0:60}"
        fi
    done < "$inc_list"

    rm -f "$inc_list"
}

if [ ! -f "$SOURCES" ]; then
    echo "[ERROR] sources.txt not found at $SOURCES"
    exit 1
fi

source_count=$(grep -cvE '^\s*$|^#' "$SOURCES" 2>/dev/null || echo "0")
echo ">> Found $source_count source URLs in sources.txt"
echo ">> Downloading filter lists..."
echo ""

total=0
success=0
failed=0
skipped=0
includes_found=0

while IFS= read -r url; do
    [[ -z "$url" || "$url" =~ ^# ]] && continue

    now=$(date +%s)
    if [ $((now - start_time)) -gt "$TOTAL_TIMEOUT" ]; then
        echo "   [!] Total timeout (${TOTAL_TIMEOUT}s) reached, stopping downloads"
        break
    fi

    total=$((total + 1))
    filename="$TEMP_DIR/list_${total}.txt"

    if curl -s -L --compressed --max-time "$DOWNLOAD_TIMEOUT" --retry 1 --retry-delay 3 -o "$filename" "$url" 2>/dev/null; then
        if validate_filter_list "$filename" "$url"; then
            lines=$(wc -l < "$filename" | tr -d ' ')
            echo "   [OK] $lines lines — ${url:0:80}"
            success=$((success + 1))

            inc_count=$(grep -c '^!#include ' "$filename" 2>/dev/null || true)
            inc_count=${inc_count:-0}
            if [ "$inc_count" -gt 0 ]; then
                echo "      Resolving $inc_count includes..."
                resolve_includes "$filename" "$url" 0
                includes_found=$((includes_found + inc_count))
            fi
        else
            rm -f "$filename"
            skipped=$((skipped + 1))
        fi
    else
        echo "   [FAIL] ${url:0:80}"
        rm -f "$filename"
        failed=$((failed + 1))
    fi
done < "$SOURCES"

inc_downloaded=$(find "$INCLUDE_DIR" -name 'inc_*.txt' 2>/dev/null | wc -l | tr -d ' ')

echo ""
echo ">> Downloaded $success/$total lists ($failed failed, $skipped skipped)"
echo ">> Resolved $inc_downloaded included sub-files"
echo ">> Processing rules..."

{
    for f in "$TEMP_DIR"/list_*.txt; do
        [ -f "$f" ] && { cat "$f"; printf '\n'; }
    done
    for f in "$INCLUDE_DIR"/inc_*.txt; do
        [ -f "$f" ] && { cat "$f"; printf '\n'; }
    done
} | grep -v '^\s*$' \
  | grep -v '^!' \
  | grep -vE '\[Adblock' \
  | grep -vE '^[[:space:]]*#($|[^#@?])' \
  | grep -vE '^#+$' \
  | grep -vE '<[a-zA-Z/][^>]*>' \
  | sed 's/^[[:space:]]*//' \
  | grep -v '^\s*$' \
  | grep -vE '[,$]app=' \
  | grep -vE '[,$]denyallow=' \
  | grep -vE '\-abp-properties\(' \
  > "$TEMP_DIR/all_rules_raw.txt" || true

if [ ! -s "$TEMP_DIR/all_rules_raw.txt" ]; then
    echo "   [ERROR] No rules collected — check network and source URLs"
    exit 1
fi

echo "   Raw rules: $(wc -l < "$TEMP_DIR/all_rules_raw.txt" | tr -d ' ')"

grep -E 'youtube\.com.*##[+]js[(]trusted-' "$TEMP_DIR/all_rules_raw.txt" \
    > "$TEMP_DIR/youtube_trusted.txt" 2>/dev/null || true
yt_trusted=$(wc -l < "$TEMP_DIR/youtube_trusted.txt" | tr -d ' ')
echo "   YouTube bypass scriptlets preserved: $yt_trusted"

grep -vE 'youtube\.com.*##' "$TEMP_DIR/all_rules_raw.txt" \
    > "$TEMP_DIR/all_rules_no_yt_cosmetic.txt" 2>/dev/null || true
stripped=$(( $(wc -l < "$TEMP_DIR/all_rules_raw.txt" | tr -d ' ') - $(wc -l < "$TEMP_DIR/all_rules_no_yt_cosmetic.txt" | tr -d ' ') ))
echo "   YouTube cosmetic/scriptlet rules stripped: $stripped"

cat "$TEMP_DIR/all_rules_no_yt_cosmetic.txt" "$TEMP_DIR/youtube_trusted.txt" \
    > "$TEMP_DIR/all_rules_clean.txt"

sort -u "$TEMP_DIR/all_rules_clean.txt" > "$TEMP_DIR/all_rules_dedup.txt"
echo "   After dedup: $(wc -l < "$TEMP_DIR/all_rules_dedup.txt" | tr -d ' ')"

subscription_count=$(wc -l < "$TEMP_DIR/all_rules_dedup.txt" | tr -d ' ')
total_rules=$subscription_count

timestamp=$(date -u '+%Y-%m-%d %H:%M:%S UTC')

cat > "$OUTPUT" << HEADER
! Title: Adblock Filter List
! Description: Comprehensive ads, privacy & annoyance protection
! Last updated: ${timestamp}
! Expires: 1 day
! Homepage: https://github.com/anT0ny54/filter-lists
! License: https://github.com/SamirPaulb/filter-lists/blob/main/LICENSE
! Total rules: ${total_rules} (${subscription_count} from ${success} sources)
!
! Auto-generated by GitHub Actions. Do not edit directly.
! To modify: edit sources.txt and push.
!
! SETUP: Subscribe to this single URL in your browser:
!   https://raw.githubusercontent.com/anT0ny54/filter-lists/refs/heads/main/filters.txt
!
!
! ==============================
! SUBSCRIPTION RULES (merged from ${success} sources)
! ==============================
HEADER

cat "$TEMP_DIR/all_rules_dedup.txt" >> "$OUTPUT"

end_time=$(date +%s)
elapsed=$((end_time - start_time))

echo ""
echo ">> Output: $OUTPUT"
echo ">> Total rules: $total_rules ($subscription_count subscription)"
echo ">> Completed in ${elapsed}s"
echo ">> Done!"
