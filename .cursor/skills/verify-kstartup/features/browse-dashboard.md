# Browse the dashboard

The user opens the GitHub Pages site and sees announcement cards with tiers. The live pool is `recommendations.json`. The default page `index.html` still bakes a stale `ITEMS` array.

## Sub-features

- `page-loads` returns HTTP 200 for `/index.html`.
- `pool-json` returns HTTP 200 for `/recommendations.json` with an `items` array.
- `title-visible` includes `신혼생활 공고 매칭 대시보드` in the HTML.
- `stale-bake` is a known gap. `ITEMS` length may not equal the JSON pool.

## How to get to it (user POV)

- Open the GitHub Pages URL in a browser.
- Open `index.html` via a local `http.server`.
- Open `recommendations.json` as raw JSON.

## Driving it with curl

Preconditions:

- `python3 -m http.server 8765 --bind 127.0.0.1` is running from the repo root.
- Doctor HTTP checks pass.

- **Load page.** `curl -sf -D - -o /tmp/kstartup-index.html http://127.0.0.1:8765/index.html`. Status 200. Body contains `신혼생활 공고 매칭 대시보드`.
- **Load pool.** `curl -sf http://127.0.0.1:8765/recommendations.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['last_updated'], len(d['items']))"`. Prints a date and a count greater than 0.
- **Proof.** Save both outputs under `scratch/agent-friendly/proof/browse-dashboard.txt`. Include the JSON `last_updated` and the HTML title.

## Gotchas

- `index.html` does not fetch the JSON. A fresh pool can coexist with a stale page. Report both counts. Do not treat equal counts as required until PR-2.
- File URLs skip `fetch`. Always use the HTTP server.
- Port 8765 must be the instance this run started.
