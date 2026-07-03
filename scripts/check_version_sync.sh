#!/usr/bin/env bash
# Fail unless every package manifest's version equals the release tag.
#
# Each ecosystem stores the version in its own canonical form, so we normalize
# before comparing:
#   - npm  (package.json)   keeps the tag verbatim:      2026.7.3-alpha.1
#   - Python (pyproject.toml) uses PEP 440 canonical form: 2026.7.3a1
#
# Usage: scripts/check_version_sync.sh v2026.7.3-alpha.1
#        (defaults to $GITHUB_REF_NAME when no argument is given)
set -euo pipefail

tag="${1:-${GITHUB_REF_NAME:-}}"
tag="${tag#v}"
if [ -z "$tag" ]; then
  echo "::error::no tag given (arg or GITHUB_REF_NAME)"; exit 1
fi

root="$(cd "$(dirname "$0")/.." && pwd)"
rc=0

# npm keeps the version VERBATIM.
pkg="$(node -p "require('$root/frontend/package.json').version")"
if [ "$pkg" != "$tag" ]; then
  echo "::error file=frontend/package.json::version ($pkg) != tag ($tag)"; rc=1
fi

# Python uses the PEP 440 canonical form: -alpha.→a, -beta.→b, -rc.→rc.
pep="$(printf '%s' "$tag" | sed -E 's/-alpha\./a/; s/-beta\./b/; s/-rc\./rc/')"
py="$(python3 -c "import tomllib; print(tomllib.load(open('$root/backend/pyproject.toml','rb'))['project']['version'])")"
if [ "$py" != "$pep" ]; then
  echo "::error file=backend/pyproject.toml::version ($py) != expected ($pep)"; rc=1
fi

if [ "$rc" -eq 0 ]; then
  echo "version sync OK: all manifests match tag $tag"
fi
exit "$rc"
