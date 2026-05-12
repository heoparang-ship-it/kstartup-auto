"""founder-gov-radar v10 sources package.

각 모듈은 Source 추상 클래스를 상속한 구체 구현을 제공한다.
`crawl_all.py` orchestrator가 SOURCES 레지스트리를 순회해 일괄 실행.
"""
from __future__ import annotations

from ._base import Source, Announcement, SourceHealthStatus, FetchError

__all__ = ["Source", "Announcement", "SourceHealthStatus", "FetchError"]
