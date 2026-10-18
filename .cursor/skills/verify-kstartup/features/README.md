# kstartup-auto verification map

Read this index, then the feature file for the path you changed.

## Baseline preconditions

- Work in a clone of `kstartup-auto` with `pip install -r requirements.txt`.
- Run `python tools/check_invariants.py --phase gate` and require exit 0.
- For HTML paths, start `python3 -m http.server 8765 --bind 127.0.0.1` from the repo root and wait until `curl -sf -o /dev/null http://127.0.0.1:8765/index.html` exits 0.
- Do not run two servers on 8765.
- Do not drive a server you did not start.

## Driving conventions

- HTML paths use `curl` against `127.0.0.1:8765`. The dashboard has no accessible names.
- CLI paths call `classify.classify` or `tools/check_invariants.py`.
- Restore `recommendations.json` after any `update.py` mutation.

## Proof and skip reporting

- Capture the command and the resulting file or HTTP body.
- HTML proof includes the served `<title>` and the JSON `last_updated`.
- CLI proof includes exit code and stdout.
- Record the feature ID with every artifact under `scratch/agent-friendly/proof/`.

## Features

- [Browse the dashboard](./browse-dashboard.md) covers the Pages HTML and the live pool JSON.
- [Classify one announcement](./classify-one.md) covers the CLI tier function.
- [Run the compile gate](./compile-gate.md) covers the CI invariant script.
- [Xcom public feed](./xcom-feed.md) covers the machine-readable 엑스컴 JSON.
