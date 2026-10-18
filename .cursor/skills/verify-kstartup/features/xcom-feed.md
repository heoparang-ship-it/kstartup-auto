# Xcom public feed

주식회사 엑스컴 collection JSON. Fields 소프트웨어, 콘텐츠, 아트·예술, 행사. Region-tier 부평 then 인천 then 전국.

## Sub-features

- `schema` is `xcom-feed-v1`.
- `region_tier` sort is 부평, 인천, 전국.
- Region does not read BIZINFO hashtags.

## How to get to it (user POV)

- Daily job writes `xcom.json`.
- GitHub Pages serves `https://heoparang-ship-it.github.io/kstartup-auto/xcom.json` from `main`.

## Driving it with python

- `python -c "from xcom_feed import build_feed; print(build_feed([], '2026-01-01T00:00:00+09:00')['schema'])"`
- `curl -sf https://heoparang-ship-it.github.io/kstartup-auto/xcom.json`

## Gotchas

- Pages serves `main`. A PR file is not live until the operator lands it.
- A source drop ≥50% exits `update.py` 2 and does not write a new pool.
