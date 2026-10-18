#!/bin/sh
set -eu
repo=$(git rev-parse --show-toplevel)
cd "$repo"
python3 tools/check_invariants.py --phase gate
echo "doctor: gate passed"
