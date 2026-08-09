#!/usr/bin/env bash
# The local gate: format, lint, tests. CI will run exactly this.
# Green means GATE_OK on the last line. Anything else is a failure.
#
# QA rule this script lives under: a gate that has never been seen red is not
# a gate. tests/test_gate_canary.py.disabled exists to prove redness on demand:
#   mv tests/test_gate_canary.py.disabled tests/test_gate_canary.py && bash scripts/gate.sh
set -u

cd "$(dirname "$0")/.."
fail=0

echo "== ruff format --check =="
python -m ruff format --check . || fail=1

echo "== ruff check =="
python -m ruff check . || fail=1

echo "== pytest =="
python -m pytest || fail=1

if [ "$fail" -ne 0 ]; then
    echo "GATE_FAILED"
    exit 1
fi
echo "GATE_OK"
