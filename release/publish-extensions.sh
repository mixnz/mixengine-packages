#!/usr/bin/env bash
#
# Publish the signed extension registry.
#
#     release/publish-extensions.sh                 # generator from mixengine master
#     release/publish-extensions.sh --ref v0.2.0    # from a tag
#     release/publish-extensions.sh --dry           # generate and check, sign nothing
#
# The roster is this repository's: data/extensions/<id>.toml. What comes from mixengine is the reader
# that decides whether a manifest is valid, and the constant that says which key an installed copy
# checks against — so a run refuses exactly what a machine would refuse, and fails before it signs if
# this repository's minisign.pub is not that constant.
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
Publish the signed extension registry.

    release/publish-extensions.sh              # generator from mixengine master
    release/publish-extensions.sh --ref TAG    # from another ref of mixnz/mixengine
    release/publish-extensions.sh --dry        # generate and check the key only

The roster is data/extensions/<id>.toml in this repository. The generator is built
from a mixengine checkout, so a manifest is judged by the same reader an installed
MixEngine uses — and the run fails before signing if minisign.pub is not the key
that build checks against.
EOF
      exit 0 ;;
    *)
      echo "Unknown argument '$1'. See release/publish-extensions.sh --help" >&2
      exit 1 ;;
  esac
done

require_gh
repo="$(repo_of)"

echo "ref:      $ref"
if [[ "$publish" == true ]]; then
  echo "publish:  true"
else
  echo "publish:  false  (generate and check the key only)"
fi
echo

dispatch publish-extensions.yml "$repo" -f "ref=$ref" -f "publish=$publish"

echo
if [[ "$publish" == true ]]; then
  cat <<EOF
Done. The signed registry is at:

    https://github.com/$repo/releases/download/index/extensions.json
    https://github.com/$repo/releases/download/index/extensions.json.minisig

That is the URL MixEngine already compiles in, so there is nothing to configure:

    mix extension available
EOF
else
  echo "Done (--dry: the document was generated and the key checked, nothing was signed)."
fi
