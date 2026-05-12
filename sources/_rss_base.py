"""RSS 기반 source 공통 구현 (KIPO/MOEL/MSIT/KOCCA 등).

RSS 목록은 제목/링크/요약만 제공하므로 `detail()` 으로 상세 HTML 추가 크롤.
개별 source는 `RSS_URL`, `agency_label`, `extract_deadline(html)` 만 오버라이드.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Optional

import feedparser

from ._base import Announcement, Source, NormalizeError, parse_kr_date, strip_html

logger = logging.getLogger("founder_gov_radar.sources._rss_base")


class RssSource(Source):
    """RSS → 목록 + (옵션) 상세 HTML. 하위 클래스에서 RSS_URL 세팅."""

    RSS_URL: str = ""
    DEFAULT_AGENCY: str = ""

    def crawl(self, since: Optional[date] = None) -> list[dict[str, Any]]:
        if not self.RSS_URL:
            raise RuntimeError(f"{self.__class__.__name__}.RSS_URL not set")
        # feedparser는 자체 HTTP. 우리 httpx rate limit 을 우회하지만
        # 단일 요청이라 수용.
        self._throttle()
        feed = feedparser.parse(self.RSS_URL)
        if getattr(feed, "bozo", False):
            logger.warning("[%s] RSS parse warning: %s", self.code, feed.get("bozo_exception"))
        items = []
        for entry in feed.entries:
            items.append({
                "title": getattr(entry, "title", ""),
                "link": getattr(entry, "link", ""),
                "published": getattr(entry, "published", ""),
                "summary": getattr(entry, "summary", ""),
                "id": getattr(entry, "id", getattr(entry, "link", "")),
            })
        logger.info("[%s] RSS: %d entries", self.code, len(items))
        return items

    def normalize(self, raw: dict[str, Any]) -> Announcement:
        title = (raw.get("title") or "").strip()
        url = raw.get("link") or raw.get("id") or ""
        if not title or not url:
            raise NormalizeError(f"{self.code} raw missing title or link")

        summary = strip_html(raw.get("summary") or "")
        published_at = self._parse_published(raw.get("published"))

        # 마감일 — RSS엔 보통 없음. 제목/요약에서 정규식으로 추출 시도
        deadline = self._extract_deadline_from_text(title + " " + summary)

        # id — URL에서 숫자 ID 추출, 없으면 URL hash
        raw_id = re.search(r"(?:seq|idx|id|articleNo|nttId)=([0-9]+)", url)
        if raw_id:
            announcement_id = self.build_announcement_id(raw_id.group(1))
        else:
            announcement_id = self.build_announcement_id(hash(url) & 0xFFFFFFFF)

        return Announcement(
            schema_version=5,
            source=self.code,
            source_label=self.label,
            id=announcement_id,
            pbancSn=None,
            title=title,
            agency=self.DEFAULT_AGENCY or self.label,
            url=url,
            deadline=deadline,
            published_at=published_at,
            structured={"summary": summary, **raw},
        )

    # ---- 유틸 ----

    @staticmethod
    def _parse_published(s: str) -> Optional[str]:
        """RSS의 published 필드를 'YYYY-MM-DD' 로 변환."""
        if not s:
            return None
        # RFC 822: "Mon, 22 Jan 2026 09:00:00 +0900"
        for fmt in (
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S GMT",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.date().isoformat()
            except ValueError:
                continue
        # 최후: kr 형식
        return parse_kr_date(s)

    @staticmethod
    def _extract_deadline_from_text(text: str) -> Optional[str]:
        # '~ 2026-05-31', '~2026.05.31', '마감: 2026.05.31'
        m = re.search(r"~\s*(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
        if not m:
            m = re.search(r"마감[:\s]*(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
        if not m:
            return None
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}"
