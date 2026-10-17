# Prototype results (throwaway)

Measured on 2026-10-17 against `main` at `d62868b` (pool) and `index.html` at `302f1dd`.

## Dual classifier

Command `python scratch/agent-friendly/proto_dual_classifier.py`.

- Pool size 1462.
- `--skip-crawl` would send every non-ITP row through `classify()`. 244 BIZINFO rows change tier (56 green to orange, 29 green to yellow, 114 yellow to orange, 45 orange to yellow).
- `_classify_external` vs `classify` disagree on 151 of 1207 BIZINFO rows.
- Three public functions do one job. `classify.py:classify`, `crawl_itp.py:classify_itp`, `update.py:_classify_external`.

## Dashboard drift

Command `python scratch/agent-friendly/proto_dashboard_drift.py`.

- `index.html` bakes `const ITEMS` with 504 rows. Last commit 2026-04-30.
- `recommendations.json` has 1462 rows. Last commit 2026-10-17.
- 472 of the 504 baked rows have a deadline before 2026-10-17.
- `index.html` does not fetch `recommendations.json`.
- `kstartup-dashboard.html` bakes `const DATA` and is dated 2026-04-28.

Daily Actions updates the JSON. GitHub Pages serves the April HTML. The user-facing page is stale.

## SyntaxError gate

Command `sh scratch/agent-friendly/proto_syntaxerror.sh`.

- `git show 1bf05f4^:update.py` raises `SyntaxError` on the f-string `{ 로`.
- Current `update.py` parses.
- `python tools/check_invariants.py --phase gate` is the CI form of this check.

## Timing

- `python -m compileall -q .` 0.093 s.
- `classify()` over 1462 pool rows 0.243 s.

## Repo shape

- 776 commits on `main`. 384 touch `recommendations.json`. 47 touch `*.py`. 663 are `github-actions[bot]`.
- 4802 tracked files. 4777 are JSON.
- Zero pull requests. Zero issues. Slack search for kstartup returned no messages. Notion search returned none. This workspace has no agent transcripts.
- `profile.md` claims classify v9.2. `classify.py` stamps `v8.3` / `2026-04-19`. Pool `_meta` has no `keyword_counts`.
- 239 pool rows have no `source`. 16 rows still carry v10 `best_entity` fields.
- Documented and missing. `crawl_all.py`, `classify_v10.py`, `normalize.py`, `crawl_v6.py`.
- 18 recorded Actions failures. Logs for the April cluster were not retrievable from `gh`.
