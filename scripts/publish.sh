#!/usr/bin/env bash
# Commit generated files and push them to a branch that may move underneath us.
#
# Usage:
#   publish.sh -m MESSAGE [--guard PATHSPEC]... -- PATH...
#
# The workflows check out the branch, spend minutes building, and only then
# push. If anyone pushed in the meantime the push is rejected as a
# non-fast-forward. Because everything this script publishes is generated
# output (never hand-edited), a conflict-prone `git rebase` is unnecessary:
# on rejection it fetches the new tip, resets onto it, copies the freshly
# built PATHs over the top and commits again, then retries with a short
# backoff.
#
# --guard PATHSPEC (repeatable): build *inputs*. If the new upstream tip
#   changed any of them since the commit we built from, the output we hold is
#   stale and must not be published over it. The script then exits 0 without
#   pushing; the push that moved the branch starts its own workflow run (or the
#   next scheduled run) rebuilds from the new inputs.
#
# Environment (all optional):
#   PUBLISH_REMOTE        remote name (default: origin)
#   PUBLISH_BRANCH        branch to update (default: $GITHUB_REF_NAME, else the
#                         current branch)
#   PUBLISH_MAX_ATTEMPTS  push attempts before giving up (default: 5)
#   PUBLISH_RETRY_DELAY   base backoff in seconds, multiplied by the attempt
#                         number (default: 2)
#
# Exit status: 0 published / nothing to publish / skipped on stale inputs;
# 1 push failed for good; 2 usage error.
set -Eeuo pipefail

remote="${PUBLISH_REMOTE:-origin}"
branch="${PUBLISH_BRANCH:-${GITHUB_REF_NAME:-}}"
max_attempts="${PUBLISH_MAX_ATTEMPTS:-5}"
retry_delay="${PUBLISH_RETRY_DELAY:-2}"
message=""
guards=()
paths=()

die_usage() {
  echo "publish.sh: $1" >&2
  echo "usage: publish.sh -m MESSAGE [--guard PATHSPEC]... -- PATH..." >&2
  exit 2
}

while (($#)); do
  case "$1" in
    -m) (($# >= 2)) || die_usage "-m needs a value"; message="$2"; shift 2 ;;
    --guard) (($# >= 2)) || die_usage "--guard needs a value"; guards+=("$2"); shift 2 ;;
    --) shift; paths=("$@"); break ;;
    *) die_usage "unexpected argument: $1" ;;
  esac
done
[[ -n "$message" ]] || die_usage "missing -m MESSAGE"
((${#paths[@]})) || die_usage "no PATH given"
[[ "$max_attempts" =~ ^[1-9][0-9]*$ ]] || die_usage "PUBLISH_MAX_ATTEMPTS must be a positive integer"
[[ "$retry_delay" =~ ^[0-9]+$ ]] || die_usage "PUBLISH_RETRY_DELAY must be a non-negative integer"

if [[ -z "$branch" ]]; then
  branch="$(git rev-parse --abbrev-ref HEAD)"
  [[ "$branch" != "HEAD" ]] || die_usage "detached HEAD and no PUBLISH_BRANCH / GITHUB_REF_NAME"
fi

# `git add` fails on a pathspec that is neither on disk nor tracked (for
# example reports/source-outcomes.json before its first run); skip those.
stage() {
  local p staged=()
  for p in "${paths[@]}"; do
    if [[ -e "$p" ]] || git ls-files --error-unmatch -- "$p" >/dev/null 2>&1; then
      staged+=("$p")
    fi
  done
  ((${#staged[@]})) && git add -A -- "${staged[@]}"
  return 0
}

nothing_staged() {
  git diff --cached --quiet -- "${paths[@]}"
}

stash=""
cleanup() { [[ -z "$stash" ]] || rm -rf -- "$stash"; }
trap cleanup EXIT

stage
if nothing_staged; then
  echo "No generated changes to publish"
  exit 0
fi

base="$(git rev-parse HEAD)"   # the commit the output was built from
git commit -q -m "$message"

attempt=1
while :; do
  if out="$(git push "$remote" "HEAD:refs/heads/$branch" 2>&1)"; then
    [[ -z "$out" ]] || echo "$out"
    echo "Published to $remote/$branch (attempt $attempt)"
    exit 0
  fi
  echo "$out" >&2

  # Only a moved branch is worth retrying; auth/permission/protection errors
  # would fail identically every time.
  if ! grep -Eiq 'rejected|non-fast-forward|fetch first|stale info|different commit|failed to update ref|cannot lock ref' <<<"$out"; then
    echo "::error::push failed for a reason other than a moved branch; not retrying" >&2
    exit 1
  fi
  if ((attempt >= max_attempts)); then
    echo "::error::push still rejected after $max_attempts attempts" >&2
    exit 1
  fi
  echo "::warning::$remote/$branch moved during the build; re-applying generated files on the new tip (attempt $attempt of $max_attempts)" >&2

  git fetch -q --depth=1 "$remote" "refs/heads/$branch"
  tip="$(git rev-parse FETCH_HEAD)"

  if ((${#guards[@]})); then
    stale="$(git diff --name-only "$base" "$tip" -- "${guards[@]}")"
    if [[ -n "$stale" ]]; then
      echo "::warning::build inputs changed upstream; the generated output is stale and was NOT published:" >&2
      echo "$stale" >&2
      echo "A new run triggered by that change (or the next scheduled run) will rebuild." >&2
      exit 0
    fi
  fi

  # Save our freshly built output, move onto the new tip, put it back.
  # Removing each path first propagates deletions (retention pruning).
  cleanup
  stash="$(mktemp -d)"
  for p in "${paths[@]}"; do
    if [[ -e "$p" ]]; then
      mkdir -p -- "$stash/$(dirname -- "$p")"
      cp -a -- "$p" "$stash/$p"
    fi
  done
  git reset -q --hard "$tip"
  for p in "${paths[@]}"; do
    rm -rf -- "$p"
    if [[ -e "$stash/$p" ]]; then
      mkdir -p -- "$(dirname -- "$p")"
      cp -a -- "$stash/$p" "$p"
    fi
  done
  base="$tip"

  stage
  if nothing_staged; then
    echo "Upstream already contains this generated output"
    exit 0
  fi
  git commit -q -m "$message"

  sleep "$((retry_delay * attempt))"
  attempt=$((attempt + 1))
done
