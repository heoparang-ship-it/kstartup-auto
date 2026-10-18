from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

Tier = Literal["green", "yellow", "orange"]
SourceCode = Literal["kstartup", "itp", "bizinfo", "kocca"]
Region = Literal["incheon", "national", "other"]


@dataclass(frozen=True)
class Announcement:
    schema_version: Literal[5]
    source: SourceCode
    id: str
    title: str
    agency: str
    url: str
    deadline: Optional[str]
    region: Optional[Region] = None
    tier: Optional[Tier] = None

    @classmethod
    def parse(cls, raw: dict) -> Announcement:
        raise NotImplementedError("PR-3")


def classify(item: Announcement) -> tuple[Tier, dict]:
    raise NotImplementedError("PR-3")
