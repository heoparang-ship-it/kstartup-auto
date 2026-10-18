#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def main() -> None:
    html = (REPO / "index.html").read_text(encoding="utf-8")
    match = re.search(r"const ITEMS = (\[.*?\]);", html)
    baked = json.loads(match.group(1)) if match else []
    pool = json.loads((REPO / "recommendations.json").read_text())["items"]
    print("index.html_ITEMS", len(baked))
    print("recommendations.json_items", len(pool))
    print("delta", len(pool) - len(baked))
    expired = sum(
        1 for it in baked if (it.get("deadline") or "") < "2026-10-17"
    )
    print("baked_deadlines_before_2026-10-17", expired)
    print("index.html_fetches_recommendations", "recommendations.json" in html)
    dash = (REPO / "kstartup-dashboard.html").read_text(encoding="utf-8")
    print("kstartup-dashboard.html_uses_DATA_const", "const DATA=" in dash)


if __name__ == "__main__":
    main()
