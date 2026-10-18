# Agent rules

Only rules that a machine already enforces, or that a later PR will enforce. Judgment stays in `.cursor/skills/verify-kstartup/`.

| Rule | Enforced by |
| --- | --- |
| Python files compile | `tools/check_invariants.py --phase gate` in `.github/workflows/invariants.yml` |
| `classify`, `crawl`, `sources._base` import | same gate |
| The 1bf05f4 f-string SyntaxError stays a failing fixture | `tests/fixtures/fstring_unescaped.txt` + `tests/test_check_invariants.py` |
| One `classify` entry point | `tools/check_invariants.py --phase debt` (informational until PR-3) |
| Pool rows have `source` | debt phase (until PR-3) |
| `index.html` ITEMS count equals pool size | debt phase (until PR-2) |
| `CLASSIFY_VERSION` matches `profile.md` | debt phase (until PR-3) |
| Prove a dashboard or pipeline change | `.cursor/skills/verify-kstartup/` |

Do not add a new classifier function. Route through `classify.classify`.
Do not bake pool rows into HTML. Read `recommendations.json`.
Do not commit to `main` without the invariants workflow on the branch.
