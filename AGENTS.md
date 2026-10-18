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
| Region is not parsed from hashtags | debt phase (until PR-3) |
| `load_pool` does not return an empty pool on error | debt phase (until PR-3) |
| Daily job compiles before crawl | `.github/workflows/daily.yml` Compile gate step |
| One source import must not skip the others | `update.py` imports BIZINFO and KOCCA separately |
| KOCCA uses selectolax lexbor | `sources/kocca.py` + gate import `sources.kocca` |
| Source count drop ≥50% vs last-good fails the job | `source_guard.py` in `update.py` (exit 2, `source_drop_warning.txt`) |
| Public Xcom JSON | `xcom_feed.py` writes `xcom.json` |
| Prove a dashboard or pipeline change | `.cursor/skills/verify-kstartup/` |

Do not add a new classifier function. Route through `classify.classify`.
Do not bake pool rows into HTML. Read `recommendations.json`.
Do not commit to `main` without the invariants workflow on the branch.
