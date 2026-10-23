#!/usr/bin/env bash
# Run a command; on failure surface the tail of its output as a GitHub error annotation
# (visible on the run summary page without opening the raw logs).
set -o pipefail
out="$(mktemp)"
"$@" 2>&1 | tee "$out"
status=${PIPESTATUS[0]}
if [ "$status" -ne 0 ]; then
  msg="$(tail -n 25 "$out" | tr '\n' '|' | cut -c1-1800)"
  echo "::error title=Step failed: $1 ${2:-}::${msg//$'\r'/}"
fi
exit "$status"
