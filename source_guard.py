#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent
LAST_GOOD_FILE = REPO / "source_counts.json"
WARNING_FILE = REPO / "source_drop_warning.txt"
DROP_RATIO = 0.5


def source_of(item: dict) -> str:
    src = item.get("source")
    if src:
        return str(src)
    if str(item.get("pbancSn") or "").startswith("itp_"):
        return "itp"
    return "kstartup"


def count_by_source(items: list) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for it in items:
        counts[source_of(it)] += 1
    return dict(counts)


def load_last_good(path: Path = LAST_GOOD_FILE) -> dict[str, int]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    counts = data.get("counts") if isinstance(data, dict) else None
    if not isinstance(counts, dict):
        return {}
    return {str(k): int(v) for k, v in counts.items()}


def save_last_good(counts: dict[str, int], as_of: str, path: Path = LAST_GOOD_FILE) -> None:
    payload = {"as_of": as_of, "counts": dict(sorted(counts.items()))}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_drops(
    baseline: dict[str, int],
    after: dict[str, int],
    *,
    ratio: float = DROP_RATIO,
) -> list[str]:
    drops: list[str] = []
    for src, prev in sorted(baseline.items()):
        if prev <= 0:
            continue
        now = int(after.get(src, 0))
        if now <= prev * ratio:
            pct = 100.0 * (prev - now) / prev
            drops.append(f"{src}: {prev} -> {now} (drop {pct:.0f}%)")
    return drops


def write_drop_warning(drops: list[str], path: Path = WARNING_FILE) -> None:
    body = "SOURCE DROP >=50%\n" + "\n".join(drops) + "\n"
    path.write_text(body, encoding="utf-8")
    print(body, end="", file=__import__("sys").stderr)
