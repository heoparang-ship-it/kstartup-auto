# Agent-friendly kstartup-auto plan

This program makes the daily announcement matcher safe for agents to change. The founder reads a dashboard that tracks the live pool. Agents have one crawl path, one classify path, and a compile gate. The operator lands PR-1 through PR-4. Nothing in this program merges itself.

## How to read this

One box is one unit of work. Every box names the evidence that checks it. A nested box is a sub-step of the box above it. Check a box only when its evidence exists, a file, a log line, a screenshot, a test run, or a SHA. The body is a how-to. The appendices explain and record.

The program runs `pstack/skills/poteto-mode/playbooks/autopilot-stack.md`. The operator lands PR-1, PR-2, PR-3, and PR-4. Owners stop at STACK-READY.

Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

## Program checklist

### Arm the program

- [ ] State the protocol and this plan to the operator, then stop. Start execution only on the operator's explicit go.
- [ ] Read these from trunk at program start. Re-read them at every tick.
  - [ ] `git show origin/main:pstack/skills/poteto-mode/playbooks/autopilot-stack.md`
  - [ ] `git show origin/main:pstack/skills/swarm/SKILL.md`
  - [ ] `git show origin/main:.cursor/skills/verify-kstartup/SKILL.md`
  - [ ] `git show origin/main:pstack/skills/poteto-mode/playbooks/opening-a-pr.md`
  - [ ] `git show origin/main:pstack/skills/correct/SKILL.md`
  - [ ] `git show origin/main:tools/check_invariants.py`
- [ ] On the operator's go, arm the audit tick as `/loop 1h` with the tick prompt below. Never leave the cadence to memory.
- [ ] Use this tick prompt, verbatim. "Re-read the execution playbook from trunk. Audit the operation against it and fix drift in this tick. Probe every active lane and judge progress by side effects only. Stand down a stuck lane and dispatch its replacement now. Then post a short status message to the operator in chat only when the audit found a tracked change that no earlier status message reported, such as a PR opened, a code-ready head, a round launched or closed, a verdict, a merge, a stuck agent and the action taken, a blocker added or cleared, or a decision only the operator can make. Name every such change and nothing else. Do not repeat a table, the merged list, or an unchanged blocker. If the audit found none, end the turn with no reply text. Either way, log this tick's row in your decision trail. The row names the items reported, or none."
- [ ] On the operator's hold or stand-down, send every owner a zero-writes order at once.

### Spawn owners

- [ ] Spawn one owner per PR with the full lifecycle the execution playbook names.
- [ ] Follow this dependency graph. Start dependent work only after its parent merges, or base it on the parent branch when the execution playbook stacks.
  - [ ] PR-1 is first. It branches from `main`.
  - [ ] PR-2 after PR-1.
  - [ ] PR-3 after PR-2.
  - [ ] PR-4 after PR-3.
- [ ] Hold the file boundaries. PR-1 touches `tools/`, `tests/`, `.github/workflows/invariants.yml`, and `.github/workflows/daily.yml`. PR-2 touches `index.html` and dashboard scripts. PR-3 touches `classify.py`, `update.py`, `crawl_itp.py`, and `sources/bizinfo.py`. PR-4 touches `sources/` and `crawl*.py`.
- [ ] Hold the review gate. PR-2 changes an interaction. It waits for the operator's review in chat with screenshots and a video before merge.

### PR mechanics, for every PR

- [ ] Resolve the forge once. Default to `gh`; if `command -v origin` succeeds and Origin can resolve the repository, use `origin pr` for every PR operation. Record any fallback to `gh`. Never require `gt`.
- [ ] Open the PR ready, never draft, per **Opening a PR**. Use the run's built-in PR tool when it has one, else `origin pr create --status open --base <base-branch>` or `gh pr create --base <base-branch>` according to the resolved forge. A stack child targets its parent branch.
- [ ] Run the repo's lint and typecheck once before the PR-facing push. Push with hooks on.
- [ ] Run `/deslop` before each commit and `/no-comments` before review.
- [ ] Triage every Bugbot and security-reviewer comment per `../references/bugbot-triage.md`.
- [ ] Rebase onto current trunk before the code-ready report and babysit. Keep that merge base in fix rounds. Rebase again only at merge prep, on a `git merge-tree` conflict with trunk, or on a CI failure that comes from a change on trunk.

### Verdict and merge, for every PR

- [ ] A full swarm runs once, at the code-ready head. Another full swarm runs only for new behavior, a redesign, or a large new diff. A rebase, a merge-conflict resolution, or a minor fix gets a single verifier at the new head. Run each full swarm per `pstack/skills/swarm/SKILL.md`. One gates lane. The ten live lanes from the PR's **Verify, live** block. The perf lane from its **Verify, perf** block. Two or more audit lanes, each with its own focus, that read the diff and the receipts and distrust the PR body. The root audits the receipts in the merge-ready report before the verdict.
- [ ] Clean only when every lane is `PASS`. Findings go back to the owner, including a defect that a lane filed as a note. A new head gets a fresh verdict, except for results that stay valid under the patch-id rule in `playbooks/shipping.md`.
- [ ] Owners report STACK-READY. They do not merge. The operator lands the contiguous verified run bottom-up.

### Boot recipe, for every live lane

Each live lane runs on its own cloud VM at the PR head. Drive the HTML with curl against `python3 -m http.server`. Drive the CLI with python. `control-ui` is not in this repo. See Appendix C.

- [ ] `git fetch origin <head-branch> && git checkout <head SHA>`.
- [ ] `pip install -r requirements.txt`. Start `python3 -m http.server 8765 --bind 127.0.0.1` from the repo root. Wait until `curl -sf -o /dev/null http://127.0.0.1:8765/index.html` exits 0.
- [ ] Deliver input only through curl and python. Read-only diagnostics are `python tools/check_invariants.py --phase gate` and `curl -sf http://127.0.0.1:8765/recommendations.json`.
- [ ] Save every screenshot to `/tmp/swarm-<pr-id>/worker-<n>/<slug>.png` and return the paths with the report.

## Add the compile gate (PR-1)

**Depends on.** None.

**Files.**

- [ ] Edit `tools/check_invariants.py`.
- [ ] Edit `.github/workflows/invariants.yml`.
- [ ] Edit `.github/workflows/daily.yml` so the compile gate runs before `update.py`.
- [ ] Create `tests/test_check_invariants.py`.
- [ ] Create `tests/fixtures/fstring_unescaped.txt`.
- [ ] Create `scratch/agent-friendly/proto_hashtag_region.py`.

**Build.**

- [ ] `check_invariants.py --phase gate` compiles every root, `sources/`, `tools/`, and `tests/` Python file and imports `classify`, `crawl`, and `sources._base`. Daily Actions runs the same gate before the crawl.

**You see.**

- [ ] `python tools/check_invariants.py --phase gate` prints `PASS gate` and exits 0. `ast.parse` of `tests/fixtures/fstring_unescaped.txt` raises `SyntaxError`.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_check_invariants.py` gate, fixture, and debt cases. Run `python -m unittest discover -s tests -v`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run `python tools/check_invariants.py --phase gate` at trunk and head. If trunk lacks the file, record that and gate a 0 exit plus stdout `PASS gate`. Save `pr1-gate-regression.png`. Pass when head exits 0 and trunk either exits 0 or lacks the script.
- [ ] Lane 2. Broken f-string fixture. Run `python -c "import ast,pathlib; ast.parse(pathlib.Path('tests/fixtures/fstring_unescaped.txt').read_text())"`. Save `pr1-fixture.png`. Pass when the process exits non-zero with `SyntaxError`.
- [ ] Lane 3. Unit suite. Run `python -m unittest discover -s tests -v`. Save `pr1-unittest.png`. Pass when exit 0.
- [ ] Lane 4. Dashboard still serves. Run `curl -sf -o /tmp/i.html http://127.0.0.1:8765/index.html`. Save `pr1-html.png`. Pass when status is success and the body contains `신혼생활 공고 매칭 대시보드`.
- [ ] Lane 5. Pool JSON still serves. Run `curl -sf http://127.0.0.1:8765/recommendations.json`. Save `pr1-json.png`. Pass when `items` is a non-empty list.
- [ ] Lane 6. Classify still runs. Run the Incheon one-liner from `.cursor/skills/verify-kstartup/features/classify-one.md`. Save `pr1-classify.png`. Pass when stdout contains `green` or `yellow`.
- [ ] Lane 7. Debt still reports three classifiers, nationwide hashtags as Incheon, and empty-pool reset. Run `python tools/check_invariants.py --phase debt`. Save `pr1-debt.png`. Pass when exit 1 and stderr names `classify.py:classify`, `update.py:_classify_external`, `nationwide hashtags`, and `empty pool`.
- [ ] Lane 8. Workflow file present. Run `test -f .github/workflows/invariants.yml`. Save `pr1-workflow.png`. Pass when exit 0.
- [ ] Lane 9. Doctor helper. Run `sh .cursor/skills/verify-kstartup/scripts/doctor.sh`. Save `pr1-doctor.png`. Pass when stdout contains `doctor: gate passed`.
- [ ] Lane 10. Pages second HTML. Run `curl -sf -o /dev/null http://127.0.0.1:8765/kstartup-dashboard.html`. Save `pr1-legacy-html.png`. Pass when curl exits 0.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Wall time of `python -m compileall -q .` and of `python tools/check_invariants.py --phase gate`, measured at trunk and at head.
- [ ] Probe. `/usr/bin/env bash -c "TIMEFORMAT='%R'; { time python -m compileall -q .; } 2>&1"` then the gate command, trunk then head, interleaved.
- [ ] Baseline. Record the trunk compileall 0.093 s and gate about 0.3 s first. Re-measure trunk on the execution VM.
- [ ] Rule. Head compileall above 1.0 s fails. Head gate above 2.0 s fails.

**Review gate.** None. PR-1 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Bugbot triage done.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends it to the base-branch stack and the operator lands it bottom-up.

## Wire the dashboard to the pool (PR-2)

**Depends on.** PR-1.

**Files.**

- [ ] Edit `index.html`.
- [ ] Delete the baked `const ITEMS = [...]` payload.
- [ ] Edit `fix_dashboard.py` so it no longer regex-patches baked rows.
- [ ] Delete or stop serving `kstartup-dashboard.html` as a second product page.

**Build.**

- [ ] `index.html` loads `recommendations.json` with `fetch` and renders that list. There is no second baked array.

**You see.**

- [ ] A local server shows a card count equal to `len(recommendations.json items)` in the stats row.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tools/check_invariants.py --phase debt` no longer prints an ITEMS vs pool mismatch. Run `python tools/check_invariants.py --phase debt`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run curl of `/index.html` at trunk and head and compare whether the page fetches `recommendations.json`. If trunk lacks the fetch, record that and gate the head page containing `fetch('recommendations.json'` plus a stats count equal to the JSON length. Save `pr2-fetch-regression.png`. Pass when head fetches JSON and trunk is recorded as baked.
- [ ] Lane 2. Count match. Save `pr2-count.png`. Pass when the visible total equals `len(items)` from the JSON.
- [ ] Lane 3. Green filter. Save `pr2-green.png`. Pass when the green stat matches JSON rows with `tier==green`.
- [ ] Lane 4. Expired row with a past deadline is hidden unless starred. Save `pr2-expired.png`. Pass when a row with deadline before today is absent from the default list.
- [ ] Lane 5. Raw JSON link. Save `pr2-raw.png`. Pass when `/recommendations.json` still 200.
- [ ] Lane 6. Title. Save `pr2-title.png`. Pass when `h1` still names the 신혼생활 dashboard.
- [ ] Lane 7. File URL warning. Open without the server if possible, else curl. Save `pr2-noserver.png`. Pass when the README or on-page note says fetch needs HTTP.
- [ ] Lane 8. `kstartup-dashboard.html` is not linked from `index.html`. Save `pr2-no-second.png`. Pass when the head page has no `kstartup-dashboard.html` href.
- [ ] Lane 9. Classify still works. Save `pr2-classify.png`. Pass when the Incheon one-liner still prints a tier.
- [ ] Lane 10. Gate still passes. Save `pr2-gate.png`. Pass when `python tools/check_invariants.py --phase gate` exits 0.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Time to first card list on `http://127.0.0.1:8765/index.html` plus time to fetch `recommendations.json`, at trunk and head. Trunk uses baked ITEMS so also record JSON fetch as the diff-added work.
- [ ] Probe. `curl -o /dev/null -s -w '%{time_total}'` for `/index.html` and `/recommendations.json`, trunk then head, interleaved.
- [ ] Baseline. Record trunk HTML time first. JSON is about 7 MB.
- [ ] Rule. Head HTML plus JSON fetch above 5.0 s fails. Head JSON fetch above 4.0 s fails as an absolute budget for the new work.

**Review gate.** The operator reviews before merge.

- [ ] Copy lane 2 screenshots into `scratch/agent-friendly/proof/pr-2-review-count.png`.
- [ ] Record a 30 to 60 second video of the change on a lane VM. Save it as `scratch/agent-friendly/proof/pr-2-review.mp4`.
- [ ] Post the screenshots and the video in chat. Stop at merge-ready. Wait for the operator's click.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Bugbot triage done.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends it to the base-branch stack and the operator lands it bottom-up.

## Unify classify and parse the pool (PR-3)

**Depends on.** PR-2.

**Files.**

- [ ] Edit `classify.py`.
- [ ] Edit `update.py`.
- [ ] Edit `crawl_itp.py`.
- [ ] Edit `sources/bizinfo.py` so region is not parsed from hashtags.
- [ ] Edit `tools/check_invariants.py` so debt becomes gate for one entry point, required `source`, no hashtag-region, and no empty-pool reset.

**Build.**

- [ ] `classify.classify(item)` is the only function that assigns a tier. Source-specific rules live as private helpers. `load_pool` parses each row into `Announcement`, rejects a missing `source`, and raises on unknown schema instead of returning empty items. Region comes from agency and title, never from hashtags. Goldens encode `profile.md` storytelling-bridge plus the water-industry nationwide-hashtag case, not today's stored greens.

**You see.**

- [ ] `python tools/check_invariants.py --phase both` exits 0. `--skip-crawl` on a copy of the pool does not change stored BIZINFO tiers.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] A unit that builds one BIZINFO dict and one K-Startup dict and asserts `classify` is used for both. Run `python -m unittest discover -s tests -v`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run `python scratch/agent-friendly/proto_dual_classifier.py` at trunk and head. If trunk still disagrees, record that and gate head printing `skip_crawl_disagreements 0`. Save `pr3-dual-regression.png`. Pass when head reports 0 skip-crawl disagreements.
- [ ] Lane 2. Debt is gone. Save `pr3-debt.png`. Pass when `--phase both` exits 0.
- [ ] Lane 3. Incheon synthetic still greens or yellows. Save `pr3-incheon.png`. Pass when the one-liner prints `green` or `yellow`.
- [ ] Lane 4. Missing `source` fails parse. Save `pr3-nosource.png`. Pass when a row without `source` raises a parse error.
- [ ] Lane 5. Nationwide hashtags do not make Incheon. Run a water-industry title with agency `환경부` and the nationwide hashtag string from `tools/check_invariants.py`. Save `pr3-hashtag.png`. Pass when stdout is not `green`.
- [ ] Lane 6. ITP rows still classify. Save `pr3-itp.png`. Pass when an `itp_` fixture returns a tier and does not call a public `classify_itp`.
- [ ] Lane 7. `CLASSIFY_VERSION` matches `profile.md`. Save `pr3-version.png`. Pass when both say the same version string.
- [ ] Lane 8. Gate still compiles. Save `pr3-gate.png`. Pass when `--phase gate` exits 0.
- [ ] Lane 9. Pool JSON serves. Save `pr3-json.png`. Pass when `/recommendations.json` 200.
- [ ] Lane 10. No `_classify_external` def. Save `pr3-no-ext.png`. Pass when `rg "def _classify_external" update.py` exits 1.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Time to `classify` every pool row, trunk and head.
- [ ] Probe. The dual-classifier prototype timed, trunk then head, interleaved.
- [ ] Baseline. Record the trunk 0.243 s first. Re-measure on the execution VM.
- [ ] Rule. Head above 2.0 s fails.

**Review gate.** None. PR-3 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Bugbot triage done.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends it to the base-branch stack and the operator lands it bottom-up.

## Register sources and stop bulk JSON in git (PR-4)

**Depends on.** PR-3.

**Files.**

- [ ] Create `sources/kstartup.py` wrapping `crawl.py`.
- [ ] Create `sources/itp.py` wrapping `crawl_itp.py`.
- [ ] Create `sources/registry.py` as the one list `update.py` walks.
- [ ] Edit `.github/workflows/daily.yml` so it does not `git add` `pending_pdf_score/` or `deep_analysis/`.
- [ ] Edit `.gitignore` to ignore those queues.

**Build.**

- [ ] `update.py` crawls only through `sources.registry.SOURCES`. Numbered PDF scripts stay, but their output is an artifact, not a git path.

**You see.**

- [ ] `git ls-files pending_pdf_score | wc -l` is 0 on the PR head. A dry `update.py --skip-crawl` still writes a valid `recommendations.json`.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] A unit that imports `SOURCES` and asserts `kstartup`, `itp`, `bizinfo`, and `kocca` are registered. Run `python -m unittest discover -s tests -v`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `grok-4.7-xhigh-fast` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Run `git ls-files '*.py' | wc -l` and dashboard curl at trunk and head. If trunk tracks `pending_pdf_score`, record that and gate head tracking none of those JSON files. Save `pr4-gitignore-regression.png`. Pass when head has zero tracked `pending_pdf_score` files.
- [ ] Lane 2. Registry import. Save `pr4-registry.png`. Pass when `from sources.registry import SOURCES` prints four codes.
- [ ] Lane 3. `update.py --skip-crawl` on a copy. Save `pr4-skip.png`. Pass when it exits 0 and does not drop `source` on rows.
- [ ] Lane 4. Dashboard still matches JSON. Save `pr4-dash.png`. Pass when the page total equals JSON length.
- [ ] Lane 5. Daily workflow has no `git add pending_pdf_score`. Save `pr4-yml.png`. Pass when `rg "pending_pdf_score" .github/workflows/daily.yml` finds no `git add`.
- [ ] Lane 6. Compile gate. Save `pr4-gate.png`. Pass when gate exits 0.
- [ ] Lane 7. Classify Incheon. Save `pr4-classify.png`. Pass when the one-liner prints a tier.
- [ ] Lane 8. Bizinfo adapter still imports or skips with a log, not a traceback. Save `pr4-bizinfo.png`. Pass when `python -c "import update"` exits 0.
- [ ] Lane 9. Pages HTML 200. Save `pr4-html.png`. Pass when curl of `/index.html` succeeds.
- [ ] Lane 10. `deep_analysis` is untracked or empty of new dumps. Save `pr4-da.png`. Pass when the workflow does not `git add deep_analysis/`.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. `git count-objects -vH` pack size at trunk and head, plus `--skip-crawl` wall time.
- [ ] Probe. Those two commands, trunk then head, interleaved.
- [ ] Baseline. Record trunk pack 107 MiB first. `--skip-crawl` time is unknown until the execution VM runs it.
- [ ] Rule. Head pack must be smaller than trunk. Head `--skip-crawl` above 60 s fails.

**Review gate.** None. PR-4 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Bugbot triage done.
- [ ] Rebased onto current trunk after the verdict, patch-id unchanged.
- [ ] The root appends it to the base-branch stack and the operator lands it bottom-up.

## Close the program

- [ ] Every box above is checked with its evidence.
- [ ] Reply to the operator with the report the execution playbook names.

## Appendix A. Prototype evidence

Dual classifier. Branch `cursor/agent-friendly-kstartup-899c`. Script `scratch/agent-friendly/proto_dual_classifier.py`. 244 of 1462 rows would change tier under `--skip-crawl`. SHA of the measurement is this PR head.

Dashboard drift. Script `scratch/agent-friendly/proto_dashboard_drift.py`. `index.html` 504 baked rows (2026-04-30) vs pool 1462 (2026-10-17). 472 baked deadlines are already past.

SyntaxError. Script `scratch/agent-friendly/proto_syntaxerror.sh`. Parent of [1bf05f4](https://github.com/heoparang-ship-it/kstartup-auto/commit/1bf05f4) fails `ast.parse`. Current `update.py` parses. Gate encodes that.

Hashtag region. Script `scratch/agent-friendly/proto_hashtag_region.py`. 57 BIZINFO greens cite `인천 매칭 + 창업`. 44 of those have `인천` only in hashtags. `BizinfoSource._extract_region` on the nationwide tag list returns a city list that includes `인천`. Water-industry notice `PBLN_000000000111680` is one of them.

Empty-pool reset. `update.py` `load_pool` catches `ValueError` from unknown `schema_version` and returns `items=[]`. A bad or future schema wipes the live pool on the next run.

`reds_today` residue. 300 pool rows still carry `reds_today` after the field was dropped from the writer. Dead key. Drop on rewrite. Do not classify from it.

Timing. compileall 0.093 s. classify 1462 rows 0.243 s.

Unproven until PR-4 executes. Artifact hosting for PDF queues (Actions artifacts vs a bucket). Exact Pages cache behavior after `ITEMS` is removed.

## Appendix B. Alternatives rejected

Finish v10 in place and keep JSON in git. The `Source` ABC already exists, but leaving 4777 JSON files in git is what trains agents to dump data on `main`. Interface stays wide (`update.py` plus numbered scripts plus two HTML files).

Extract a new service and delete this repo's pipeline. Hides more, but the founder already has Pages and Actions. A new host is a product move, not an agent-safety move.

Keep three classifiers and document which to call. Prose. Agents copy the nearest function. Measured 244-row drift under `--skip-crawl`.

Append-only sqlite outside git as the first cut. Needs a bucket and a fold job the founder does not run today. Graft the hashtag-region ban and the raise-on-unknown-schema behavior onto the existing JSON pool instead.

Event-sourced log with a rules DSL. `audit_green` and storytelling-bridge are not DSL facts. Graft computed goldens from `profile.md` plus the 44 hashtag-only notices. Keep stored evidence. Recompute tier through `classify` on `--skip-crawl`.

## Appendix C. Risks

pstack playbooks are not vendored in this repo. `git show origin/main:pstack/...` will fail until the plugin path is copied or the arm step reads the plugin. PR-1 watches that.

`control-ui` is absent. Live lanes use curl and python. Screenshot files may be terminal captures.

`selectolax.parser` import currently fails on selectolax 1.0 (modest backend). PR-4 must switch KOCCA to lexbor or pin selectolax. Otherwise BIZINFO/KOCCA stay skipped.

PR-2 is the only review-gated PR. A fetch-based dashboard can fail on file:// and on Pages MIME. The owner watches that.

PR-4 dropping `pending_pdf_score/` from git deletes a 4273-file queue from history going forward. 3608 of those files have no matching `pbancSn` in the live pool. The generator script stays. If the founder still scores PDFs by hand, they need an artifact download. Default is drop from git.

`load_pool` empty-reset is live until PR-3. A schema bump without a reader bump wipes `recommendations.json` on the next daily run.

## Appendix D. Links and reading list

- `profile.md` is the matching SSOT. `classify.py` must match it after PR-3.
- `sources/_base.py` `Announcement` is the domain type. Callers use it after PR-3.
- `scratch/agent-friendly/RESULTS.md` has the numbers.
- `.cursor/skills/verify-kstartup/SKILL.md` is the control skill for live lanes.
- PR-3 runs `pstack/skills/how/SKILL.md` on `update.py` before editing.
- PR-2 runs `pstack/skills/interrogate/SKILL.md` on the fetch-vs-bake choice only if a reviewer disputes Appendix A.
- Trail is this file plus `scratch/agent-friendly/RESULTS.md`.
