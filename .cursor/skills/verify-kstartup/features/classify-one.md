# Classify one announcement

The user (and the daily job) assigns a tier to one announcement. The only supported library call is `classify.classify`.

## Sub-features

- `incheon-green` returns `green` or `yellow` for an Incheon pre-startup title.
- `tuple-shape` returns `(tier, evidence)` with `classify_version` in evidence.
- `no-network` does not open a socket.

## How to get to it (user POV)

- Run the daily workflow, which calls `classify` from `update.py`.
- Call `classify.classify` from a REPL or a one-liner.

## Driving it with python

Preconditions:

- `pip install -r requirements.txt` is done.
- `python tools/check_invariants.py --phase gate` exits 0.

- **Incheon row.** `python -c "from classify import classify; t,e=classify({'title':'인천 예비창업패키지','agency':'인천창조경제혁신센터','deadline':'2099-01-01','structured':{}}); print(t, e['classify_version'])"`. stdout starts with `green` or `yellow` and contains `v8.3` until PR-3.
- **Proof.** Save stdout in `scratch/agent-friendly/proof/classify-one.txt`.

## Gotchas

- BIZINFO rows in the pool were stored by `_classify_external`. Calling `classify` on those rows is not the production path today. Use a synthetic Incheon dict for this feature until PR-3.
- `update.py --skip-crawl` currently reclassifies BIZINFO rows with `classify` and will shuffle tiers. Do not use skip-crawl as proof of classifier stability.
- Nationwide BIZINFO hashtags include `인천` as one city in a country-wide list. `BizinfoSource._extract_region` currently returns a city list that includes `인천` for that string. 44 stored greens are hashtag-only. Do not treat a green water-industry or similar nationwide notice as a pass for `incheon-green`.
