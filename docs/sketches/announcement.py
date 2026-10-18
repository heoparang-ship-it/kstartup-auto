"""Type sketch for PR-3. Not implemented. Callers import Announcement and classify.

Usage the caller writes after PR-3

    from sources.registry import SOURCES, crawl_all
    from classify import classify
    from pool import load_pool, save_pool

    raws = crawl_all(SOURCES)
    pool = load_pool()
    for raw in raws:
        item = Announcement.parse(raw)  # raises on missing source or id
        item.tier, item.evidence = classify(item)
        pool.upsert(item)
    save_pool(pool)

Illegal states the type removes

    A row with no source.
    A red+green pair of booleans. tier is Literal["green","yellow","orange"].
    Two public classify functions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

Tier = Literal["green", "yellow", "orange"]
SourceCode = Literal["kstartup", "itp", "bizinfo", "kocca"]


@dataclass(frozen=True)
class Announcement:
    schema_version: Literal[5]
    source: SourceCode
    id: str
    title: str
    agency: str
    url: str
    deadline: Optional[str]
    tier: Optional[Tier] = None

    @classmethod
    def parse(cls, raw: dict) -> Announcement:
        raise NotImplementedError("PR-3")


def classify(item: Announcement) -> tuple[Tier, dict]:
    raise NotImplementedError("PR-3. Private helpers per source, one public function.")
