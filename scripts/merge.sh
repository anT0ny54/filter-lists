#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SOURCES="$REPO_DIR/sources.txt"
OUTPUT="$REPO_DIR/filters.txt"

TEMP_DIR="$(mktemp -d)"
INCLUDE_DIR="$TEMP_DIR/includes"
mkdir -p "$INCLUDE_DIR"
trap 'rm -rf "$TEMP_DIR"' EXIT

DOWNLOAD_TIMEOUT=90
INCLUDE_TIMEOUT=60
TOTAL_TIMEOUT=3300
MAX_INCLUDE_DEPTH=3

start_time=$(date +%s)
echo "0" > "$TEMP_DIR/.counter"

validate_filter_list() {
  local file="$1" url="$2" lines size
  lines=$(wc -l < "$file" | tr -d ' ')
  size=$(wc -c < "$file" | tr -d ' ')

  [[ "$size" -lt 500 ]] && { echo "   [SKIP] Too small (${size} bytes) — $url"; return 1; }
  [[ "$lines" -lt 5 ]] && { echo "   [SKIP] Too few lines (${lines}) — $url"; return 1; }

  if head -20 "$file" | grep -qiE '<!doctype|<html|HTTP Status [0-9]|<title>'; then
    echo "   [SKIP] HTML/error page — $url"
    return 1
  fi

  if head -3 "$file" | grep -qE '^[[:space:]]*\{'; then
    echo "   [SKIP] JSON response — $url"
    return 1
  fi

  if file -b --mime "$file" 2>/dev/null | grep -qiE 'binary|octet-stream|executable'; then
    echo "   [SKIP] Binary content — $url"
    return 1
  fi

  return 0
}

resolve_includes() {
  local file="$1" base_url="$2" depth="$3"
  (( depth > MAX_INCLUDE_DEPTH )) && return 0

  local now
  now=$(date +%s)
  (( now - start_time > TOTAL_TIMEOUT )) && return 0

  local dir_url inc_list
  dir_url="$(printf '%s' "$base_url" | sed 's|/[^/]*$|/|')"
  inc_list="$TEMP_DIR/.inc_paths_${depth}_$RANDOM.txt"

  grep '^!#include ' "$file" 2>/dev/null | sed 's/^!#include //' | tr -d '\r' > "$inc_list" || true

  while IFS= read -r include_path; do
    [[ -z "$include_path" ]] && continue

    local include_url
    if [[ "$include_path" =~ ^https?:// ]]; then
      include_url="$include_path"
    else
      include_url="${dir_url}${include_path}"
    fi

    local fc include_file
    fc=$(<"$TEMP_DIR/.counter")
    fc=$((fc + 1))
    echo "$fc" > "$TEMP_DIR/.counter"
    include_file="$INCLUDE_DIR/inc_${fc}.txt"

    if curl -fsSL --compressed --max-time "$INCLUDE_TIMEOUT" --retry 1 \
      -o "$include_file" "$include_url" 2>/dev/null; then

      if validate_filter_list "$include_file" "$include_url"; then
        resolve_includes "$include_file" "$include_url" $((depth + 1))
      fi
    fi
  done < "$inc_list"

  rm -f "$inc_list"
}

if [[ ! -f "$SOURCES" ]]; then
  echo "[ERROR] sources.txt not found at $SOURCES"
  exit 1
fi

source_count=$(grep -cvE '^\s*$|^#' "$SOURCES" 2>/dev/null || echo 0)
echo ">> Found $source_count source URLs in sources.txt"
echo ">> Downloading filter lists..."
echo

total=0
success=0
failed=0
skipped=0

while IFS= read -r url; do
  [[ -z "$url" || "$url" =~ ^# ]] && continue

  now=$(date +%s)
  if (( now - start_time > TOTAL_TIMEOUT )); then
    echo "   [!] Total timeout reached, stopping downloads"
    break
  fi

  total=$((total + 1))
  filename="$TEMP_DIR/list_${total}.txt"

  if curl -fsSL --compressed --max-time "$DOWNLOAD_TIMEOUT" --retry 1 --retry-delay 3 \
    -o "$filename" "$url" 2>/dev/null; then

    if validate_filter_list "$filename" "$url"; then
      lines=$(wc -l < "$filename" | tr -d ' ')
      echo "   [OK] $lines lines — ${url:0:90}"
      success=$((success + 1))

      if grep -q '^!#include ' "$filename" 2>/dev/null; then
        echo "      Resolving includes..."
        resolve_includes "$filename" "$url" 0
      fi
    else
      rm -f "$filename"
      skipped=$((skipped + 1))
    fi
  else
    echo "   [FAIL] ${url:0:90}"
    rm -f "$filename"
    failed=$((failed + 1))
  fi
done < "$SOURCES"

echo
echo ">> Downloaded $success/$total lists ($failed failed, $skipped skipped)"
echo ">> Processing rules..."

# Create intermediate file to avoid broken pipe issues
MERGED_RULES="$TEMP_DIR/merged_rules.txt"
{
  for f in "$TEMP_DIR"/list_*.txt; do
    [[ -f "$f" ]] && { cat "$f"; printf '\n'; }
  done
  for f in "$INCLUDE_DIR"/inc_*.txt; do
    [[ -f "$f" ]] && { cat "$f"; printf '\n'; }
  done
} > "$MERGED_RULES"

# Process with Python
python3 - "$TEMP_DIR" < "$MERGED_RULES" > "$TEMP_DIR/final_rules.txt" <<'PY'
import sys, re
from collections import OrderedDict

def canon_domain_list(s):
    parts = []
    for p in s.split(","):
      p = p.strip()
      if p and p not in parts:
        parts.append(p)
    parts.sort()
    return ",".join(parts)

def normalize_cosmetic(rule):
    # Normalize domain list before ## / #@#
    m = re.match(r'^\s*([^#]+?)(##|#@#)(.*)$', rule)
    if not m:
        return rule.strip()

    domains, sep, sel = m.group(1).strip(), m.group(2), m.group(3).strip()
    domains = canon_domain_list(domains)

    # Normalize whitespace in selector only a little; keep ABP-compatible syntax
    sel = re.sub(r'\s+', ' ', sel)
    sel = sel.replace(" ,", ",").replace(", ", ",")
    return f"{domains}{sep}{sel}" if domains else f"{sep}{sel}"

def rule_key(rule):
    r = rule.strip()

    # Cosmetic rules
    if "##" in r or "#@#" in r:
        r = normalize_cosmetic(r)

        # Lowercase domain hostnames in domain list only
        m = re.match(r'^([^#]+?)(##|#@#)(.*)$', r)
        if m:
          doms = ",".join(sorted(set(d.strip().lower() for d in m.group(1).split(",") if d.strip())))
          return f"{doms}{m.group(2)}{m.group(3).strip()}"

    # Network rules: normalize whitespace only
    r = re.sub(r'\s+', '', r)
    return r

rules = []
for raw in sys.stdin:
    line = raw.rstrip("\n").strip()
    if not line:
        continue
    if line.startswith("!") or line.startswith("[") or line.startswith("#"):
        continue
    if "<" in line and ">" in line and not ("##" in line or "#@#" in line):
        continue
    if "youtube.com" in line and "##+js(trusted-" in line:
        # keep trusted youtube scriptlets
        pass
    elif "youtube.com" in line and "##" in line:
        # drop youtube cosmetic rules as in original
        continue

    # remove unsupported / noisy patterns from original script
    if re.search(r'(?:^|[,$])(?:app|denyallow)=', line):
        continue
    if "-abp-properties(" in line:
        continue

    rules.append(line)

# Preserve last wins for duplicates after canonicalization
seen = OrderedDict()
for r in rules:
    k = rule_key(r)
    seen[k] = normalize_cosmetic(r) if ("##" in r or "#@#" in r) else r.strip()

# Sort alphabetically by canonical key
for k in sorted(seen.keys(), key=lambda x: x.lower()):
    print(seen[k])
PY

if [[ ! -s "$TEMP_DIR/final_rules.txt" ]]; then
  echo "[ERROR] No rules collected."
  exit 1
fi

total_rules=$(wc -l < "$TEMP_DIR/final_rules.txt" | tr -d ' ')
timestamp=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
version="v$(date -u '+%Y.%m.%d.%H%M')"

cat > "$OUTPUT" <<HEADER
! Title: Adblock Filter List
! Version: ${version}
! Last updated: ${timestamp}
! Expires: 1 day
! Homepage: https://github.com/anT0ny54/filter-lists
! License: https://github.com/SamirPaulb/filter-lists/blob/main/LICENSE
! Total rules: ${total_rules} from ${success} sources
!
! Auto-generated. Do not edit directly.
! To modify: edit sources.txt and rebuild.
!
! SUBSCRIPTION
HEADER

cat "$TEMP_DIR/final_rules.txt" >> "$OUTPUT"

elapsed=$(( $(date +%s) - start_time ))
echo
echo ">> Output: $OUTPUT"
echo ">> Total rules: $total_rules"
echo ">> Completed in ${elapsed}s"
echo ">> Done!"
