#!/usr/bin/env bash
# Map a CalVer tag's pre-release suffix to the moving channel pointers this
# build advances. Channels cascade by maturity: a more mature release also
# advances every less-mature channel.
#
#   *-alpha.*  -> alpha
#   *-beta.*   -> beta alpha
#   *-rc.*     -> rc
#   (no suffix)-> stable beta alpha
#
# Usage: scripts/derive_channels.sh v2026.7.3-alpha.1
#        (defaults to $GITHUB_REF_NAME when no argument is given)
set -euo pipefail

ref="${1:-${GITHUB_REF_NAME:-}}"
ref="${ref#v}"

case "$ref" in
  *-alpha.*) channels="alpha" ;;
  *-beta.*)  channels="beta alpha" ;;
  *-rc.*)    channels="rc" ;;
  *)         channels="stable beta alpha" ;;
esac

echo "$channels"
