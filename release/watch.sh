#!/usr/bin/env bash
#
# Run the upstream watch now rather than waiting for its morning schedule.
#
#     release/watch.sh
#
# The workflow's `dry` input defaults to **true**, so a dispatch from the web page only prints the
# plan — it builds nothing, publishes nothing and leaves the issue exactly as it was, which reads as
# "the issue does not close". The default here is the real run, the way the schedule does it, and
# `--dry` is the way to only look.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=release/_dispatch.sh
source "$here/_dispatch.sh"

dry=false
for arg in "$@"; do
  case "$arg" in
    --dry) dry=true ;;
    -h|--help)
      cat <<'EOF'
Run the upstream watch now rather than waiting for its morning schedule.

    release/watch.sh          # build new patches, publish the index, write or close the issue
    release/watch.sh --dry    # print the plan only, touch nothing

A real run can take hours when there is a lot to build. It is the same run the
schedule makes, so a version it builds is not built again the next morning.
EOF
      exit 0 ;;
    *)
      echo "Unknown argument '$arg'. See release/watch.sh --help" >&2
      exit 1 ;;
  esac
done

require_gh
repo="$(repo_of)"

if [[ "$dry" == true ]]; then
  echo "dry:      true  (print the plan only, nothing is built, published or reported)"
else
  echo "dry:      false"
fi
echo

dispatch watch-upstream.yml "$repo" -f "dry=$dry"

echo
if [[ "$dry" == true ]]; then
  echo "Done (--dry: the plan is in the run's log, under the watch step)."
  exit 0
fi

open="$(gh issue list --repo "$repo" --label upstream-watch --state open \
          --json number --jq '.[0].number // empty')"
if [[ -z "$open" ]]; then
  echo "Done. No open upstream-watch issue: nothing needs a person."
else
  cat <<EOF
Done. Something needs a person — the steps are in the issue:

    https://github.com/$repo/issues/$open
EOF
fi
