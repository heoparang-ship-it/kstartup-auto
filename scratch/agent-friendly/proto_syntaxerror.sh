#!/bin/sh
# Throwaway. Prove compileall would have caught commit 1bf05f4's parent.
# Decision this answers: is a compile CI gate enough for the SyntaxError class?
set -eu
repo=$(git rev-parse --show-toplevel)
git -C "$repo" show 1bf05f4^:update.py > /tmp/kstartup-update-broken.py
if python3 -c 'import ast,pathlib; ast.parse(pathlib.Path("/tmp/kstartup-update-broken.py").read_text())'; then
  echo "UNEXPECTED compile success"
  exit 1
fi
echo "PASS parent of 1bf05f4 is SyntaxError (compileall would fail the push)"
python3 -c 'import ast,pathlib; ast.parse(pathlib.Path("'"$repo"'/update.py").read_text())'
echo "PASS current update.py parses"
