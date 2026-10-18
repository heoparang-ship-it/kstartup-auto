#!/usr/bin/env python3
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from classify import classify  # noqa: E402
from crawl_itp import classify_itp  # noqa: E402
from sources._base import Announcement  # noqa: E402
import update as u  # noqa: E402


def main() -> None:
    items = json.loads((REPO / "recommendations.json").read_text())["items"]
    skip = collections.Counter()
    for it in items:
        sn = str(it.get("pbancSn", ""))
        stored = it.get("tier")
        if sn.startswith("itp_"):
            got, _ = classify_itp(it)
        else:
            got, _ = classify(it)
        if got != stored:
            skip[(it.get("source") or "legacy", stored, got)] += 1
    print("skip_crawl_disagreements", sum(skip.values()), "of", len(items))
    for key, n in skip.most_common():
        print(" ", key, n)

    ext = collections.Counter()
    n_biz = 0
    for it in items:
        if it.get("source") != "bizinfo":
            continue
        n_biz += 1
        ann = Announcement(
            schema_version=5,
            source="bizinfo",
            source_label=it.get("source_label") or "",
            id=it.get("id") or it.get("pbancSn") or "",
            title=it.get("title") or "",
            agency=it.get("agency") or "",
            url=it.get("url") or "",
            deadline=it.get("deadline") or None,
            published_at=None,
            region=(it.get("structured") or {}).get("region"),
            structured=it.get("structured") or {},
        )
        t_ext, _ = u._classify_external(ann)
        t_ks, _ = classify(it)
        if t_ext != t_ks:
            ext[(t_ext, t_ks)] += 1
    print("bizinfo _classify_external vs classify", sum(ext.values()), "of", n_biz)
    for key, n in ext.most_common():
        print(" ", key, n)


if __name__ == "__main__":
    main()
