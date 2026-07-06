#!/usr/bin/env bash
# Enforce the 80-column prose rule (module-documentation) on Markdown docs.
#
# Exempts the kit's sanctioned wide lines: fenced code blocks, table rows,
# lines carrying a URL, and lines that are (or contain) a Markdown link/path
# that cannot be broken. Takes the files to check as arguments (pre-commit
# passes the staged Markdown files).
set -euo pipefail

violations=$(awk '
  FNR == 1 { code = 0 }
  /^```/   { code = !code; next }   # toggle fenced code block
  code     { next }
  /^[[:space:]]*\|/       { next }  # table rows
  /https?:\/\//           { next }  # URLs
  /\]\(/                  { next }  # Markdown links / paths
  length > 80 { printf "%s:%d: %d columns (>80)\n", FILENAME, FNR, length }
' "$@")

if [ -n "$violations" ]; then
  echo "Markdown prose exceeds 80 columns:" >&2
  echo "$violations" >&2
  exit 1
fi
