#!/usr/bin/env bash
# P11.2: watch a soak workdir the way the 24h run taught us to.
#
# Check ORDER matters: the completion artifact FIRST, the process second.
# The initiator exits immediately after writing final.json, so a watcher
# that checks the PID first reports "DEAD" at the finish line (it did).
#
#   watch_soak.sh <workdir> <pid> [interval_s]
set -u
wd="$1"; pid="$2"; interval="${3:-120}"
while true; do
  if [ -f "$wd/final.json" ]; then
    echo "SOAK COMPLETE: $wd/final.json"
    exit 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "SOAK DEAD: pid $pid gone with no final.json; last status:"
    cat "$wd/status.json" 2>/dev/null
    exit 1
  fi
  if [ -f "$wd/status.json" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$wd/status.json") ))
    [ "$age" -gt 300 ] && echo "SOAK STALLED: status.json ${age}s old"
  fi
  sleep "$interval"
done
