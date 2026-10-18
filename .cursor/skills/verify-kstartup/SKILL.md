---
name: verify-kstartup
description: Drive the kstartup-auto GitHub Pages dashboard and the Python pipeline the way a user does. Use after changing classify, update, crawl, dashboard HTML, or CI.
---

# Verify kstartup-auto

Primary surface is the static dashboard (`index.html`) plus `recommendations.json`. The pipeline is a set of CLI scripts. There is no app server.

## Launch

From the repo root.

```sh
python3 -m http.server 8765 --bind 127.0.0.1
```

Ready when `curl -sf -o /dev/null http://127.0.0.1:8765/index.html` exits 0. The page is usable without login. Pool data is the committed `recommendations.json`.

Teardown is SIGTERM to the `http.server` PID this run started. Do not `pkill -f http.server`.

For CLI-only checks, skip the server. Install deps once with `pip install -r requirements.txt`.

## Doctor

Read-only.

```sh
python tools/check_invariants.py --phase gate
curl -sf -o /dev/null http://127.0.0.1:8765/index.html
curl -sf http://127.0.0.1:8765/recommendations.json | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('items')"
```

Doctor passes when the gate exits 0, the HTML returns 200, and the JSON has an `items` list. If the server is not up, run only the gate and say the HTTP checks were skipped.

## Drive

HTML. `curl` the page and JSON. Prefer `h1` text `신혼생활 공고 매칭 대시보드` and the `items` length in JSON. There are no ARIA roles on the baked dashboard. Do not click coordinates.

CLI. Call library functions, not GitHub Actions.

```sh
python -m compileall -q classify.py update.py crawl.py
python -c "from classify import classify; print(classify({'title':'인천 예비창업패키지','agency':'인천창조경제혁신센터','deadline':'2099-01-01','structured':{}})[0])"
```

Do not run `update.py` against production sources unless the task is the crawler itself. It writes `recommendations.json` and needs `BIZINFO_SERVICE_KEY` for BIZINFO.

## Evidence

Proof goes in `scratch/agent-friendly/proof/` and survives cleanup.

- HTML. Save the first 20 lines of `index.html` as served (`curl -s http://127.0.0.1:8765/index.html | head`). Save `recommendations.json` `last_updated` and `len(items)`.
- CLI. Save the command, stdout, stderr, and exit code.
- Side effects. After a classify call, the return value is the proof. After an `update.py` run, `git diff --stat recommendations.json` is the proof. Mocks are not used.

A dry-run name is not proof. Observe the file.

## Cleanup

Kill only the server PID this run exported as `KSTARTUP_VERIFY_PID`. Leave `scratch/agent-friendly/proof/` in place.

## Helpers

`scripts/doctor.sh` from this skill directory. Run `sh .cursor/skills/verify-kstartup/scripts/doctor.sh` from the repo root. It runs the gate. It does not start a server.
