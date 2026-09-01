#!/usr/bin/env bash
#
# Publish the blueprint gallery as signed files.
#
#     release/publish-blueprints.sh                 # from mixengine master
#     release/publish-blueprints.sh --ref v0.2.0    # from a tag
#     release/publish-blueprints.sh --dry           # read and check, sign nothing
#
# The manifests are read out of a mixnz/mixengine checkout the workflow makes, never out of this
# repository: there is one gallery and it lives over there. What this repository owns is the key
# that vouches for it — and the run proves that key is the one MixEngine compiles in before it signs
# a single file.
#
# `publish` defaults to false in the workflow, the way `release` does in the builds, so the default
# here is to actually publish and `--dry` is the way to only check.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=release/_dispatch.sh
source "$here/_dispatch.sh"

publish=true
ref=master
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry) publish=false; shift ;;
    --ref) ref="${2:?--ref needs a mixengine ref}"; shift 2 ;;
    -h|--help)
      cat <<'EOF'
Publish the blueprint gallery as signed files.

    release/publish-blueprints.sh              # sign and publish, from mixengine master
    release/publish-blueprints.sh --ref TAG    # from another ref of mixnz/mixengine
    release/publish-blueprints.sh --dry        # read the gallery and check the key only

The six manifests are compiled into MixEngine and trusted there without a signature.
These files are the other channel: one downloaded by hand lands trusted because of the
`.minisig` beside it.
EOF
      exit 0 ;;
    *)
      echo "Unknown argument '$1'. See release/publish-blueprints.sh --help" >&2
      exit 1 ;;
  esac
done

require_gh
repo="$(repo_of)"

echo "ref:      $ref"
if [[ "$publish" == true ]]; then
  echo "publish:  true"
else
  echo "publish:  false  (read the gallery and check the key only)"
fi
echo

dispatch publish-blueprints.yml "$repo" -f "ref=$ref" -f "publish=$publish"

echo
if [[ "$publish" == true ]]; then
  cat <<EOF
Done. The signed gallery is at:

    https://github.com/$repo/releases/download/blueprints/<name>.toml
    https://github.com/$repo/releases/download/blueprints/<name>.toml.minisig

A downloaded pair imports trusted, with no flag naming either:

    mix blueprint import laravel.toml --overwrite

\`--overwrite\` only because every home already holds the built-in six.
EOF
else
  echo "Done (--dry: the gallery was read and the key checked, nothing was signed)."
fi
