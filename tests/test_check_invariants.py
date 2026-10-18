#!/usr/bin/env python3
from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECK = REPO / "tools" / "check_invariants.py"
FIXTURE = REPO / "tests" / "fixtures" / "fstring_unescaped.txt"


class GateTests(unittest.TestCase):
    def test_gate_exits_zero_on_current_tree(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(CHECK), "--phase", "gate"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_fstring_fixture_is_the_1bf05f4_syntaxerror(self) -> None:
        with self.assertRaises(SyntaxError):
            ast.parse(FIXTURE.read_text(encoding="utf-8"))

    def test_debt_reports_three_classify_functions(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(CHECK), "--phase", "debt"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        combined = proc.stdout + proc.stderr
        self.assertIn("classify.py:classify", combined)
        self.assertIn("crawl_itp.py:classify_itp", combined)
        self.assertIn("update.py:_classify_external", combined)
        self.assertIn("index.html ITEMS", combined)
        self.assertIn("nationwide hashtags as Incheon", combined)
        self.assertNotIn("empty pool on schema mismatch", combined)


if __name__ == "__main__":
    unittest.main()
