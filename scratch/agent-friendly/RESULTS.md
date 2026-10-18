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
- 2026-10-18 03시 daily run (`1602a5d`) dropped the pool from 1462 to 254. BIZINFO 1207 to 0. KOCCA 1 to 0. 239 rows still have no `source`. Cause. `sources/` import fails on selectolax 1.0 modest-parser deprecation, then `update.py` rewrites the pool without those adapters.

## Hashtag region (architect follow-up)

Command `python scratch/agent-friendly/proto_hashtag_region.py`.

Measured on pool `d62868b` (2026-10-17, 1462 rows, 1207 BIZINFO).

- 57 BIZINFO greens have `summary_reason` containing `인천 매칭 + 창업`.
- 44 of 57 have `인천` in hashtags and not in title or agency.
- `BizinfoSource._extract_region` on `창업,서울,부산,대구,인천,...제주` returns a city list that includes `인천`.
- Example. `PBLN_000000000111680` title `2026년 국가물산업클러스터 입주기업 모집 공고`.

On current `main` (`09d5959`, 2026-10-18) the same script prints `green_incheon_startup 0` because BIZINFO rows are gone. The `_extract_region` CODE path is unchanged. Debt still fails on the nationwide tag string.

## Empty-pool reset

`update.py` `load_pool` (lines 286-301). Unknown `schema_version` raises `ValueError`. The `except` returns a new dict with `items=[]`. Next daily run would overwrite the live pool.

## `reds_today` residue

300 current pool rows still have a `reds_today` key. The writer no longer sets it. Dead field. Drop on rewrite.

## PDF queue orphans

`pending_pdf_score/` is 4273 tracked files. 3608 have no matching `pbancSn` in the live 1462-row pool.
