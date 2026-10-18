# Run the compile gate

CI must reject Python that does not compile. This is the check that would have blocked the f-string SyntaxError in the parent of commit 1bf05f4.

## Sub-features

- `gate-pass` exits 0 on the current tree.
- `fixture-fail` parses `tests/fixtures/fstring_unescaped.txt` as SyntaxError.
- `unit` runs `python -m unittest discover -s tests -v` and exits 0.

## How to get to it (user POV)

- Push a branch. GitHub Actions runs `Invariants`.
- Run the same commands locally before push.

## Driving it with python

Preconditions:

- Repo root is the current directory.
- Python 3.12.

- **Gate.** `python tools/check_invariants.py --phase gate`. Exit 0. stdout contains `PASS gate`.
- **Fixture.** `python -c "import ast,pathlib; ast.parse(pathlib.Path('tests/fixtures/fstring_unescaped.txt').read_text())"`. Exit non-zero with `SyntaxError`.
- **Units.** `python -m unittest discover -s tests -v`. Exit 0.
- **Proof.** Save the three transcripts in `scratch/agent-friendly/proof/compile-gate.txt`.

## Gotchas

- `compileall` on the whole tree is not enough if a new package directory is added outside `tools/check_invariants.py`'s roots. Add the root to `PY_ROOTS`.
- Do not put a non-compiling `.py` fixture in the tree. Keep the SyntaxError sample as `.txt`.
