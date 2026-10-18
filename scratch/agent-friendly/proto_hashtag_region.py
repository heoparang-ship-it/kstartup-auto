#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from sources.bizinfo import BizinfoSource  # noqa: E402


def main() -> None:
    items = json.loads((REPO / "recommendations.json").read_text())["items"]
    print("pool_items", len(items))
    print("bizinfo_items", sum(1 for it in items if it.get("source") == "bizinfo"))
    n = 0
    tag_only = 0
    for it in items:
        ev = it.get("classify_evidence") or {}
        reason = ev.get("summary_reason") or ""
        if it.get("source") != "bizinfo" or it.get("tier") != "green":
            continue
        if "인천 매칭 + 창업" not in reason:
            continue
        n += 1
        title = it.get("title") or ""
        agency = it.get("agency") or ""
        tags = str((it.get("structured") or {}).get("hashtags") or "")
        if "인천" in tags and "인천" not in title and "인천" not in agency:
            tag_only += 1
    water = (
        "창업,서울,부산,대구,인천,전남광주,대전,울산,세종,경기,"
        "강원,충북,충남,전북,경북,경남,제주"
    )
    print("green_incheon_startup", n)
    print("incheon_only_in_hashtags", tag_only)
    print("extract_region", BizinfoSource._extract_region(water))


if __name__ == "__main__":
    main()
