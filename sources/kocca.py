"""KOCCA (한국콘텐츠진흥원) 지원사업 공고 어댑터.

실측 기반 (2026-04-24). RSS는 죽어있고(B0158948 → 404), 실제 지원사업 목록은
`/kocca/pims/list.do?menuNo=204104` (HTML). 인증 불필요.

현재 활성 공고: ~17건 (page 1: 10 / page 2: 7). BIZINFO에도 일부 겹치지만
BIZINFO 커버리지가 KOCCA 공고의 ~35%뿐이라 직접 크롤 유지.
생애주기 L3(콘텐츠·미디어) 직격 source 라서 놓치면 아쉬움.

목록 구조
---------
https://www.kocca.kr/kocca/pims/list.do?menuNo=204104&pageIndex=N
  <table> <tbody> <tr>
    <td>{유형: 모집공모|자유공모}</td>
    <td class="AlignLeft"><a href="/kocca/pims/view.do?intcNo=XXX">{제목}</a></td>
    <td>{등록일 yy.MM.dd}</td>
    <td>{접수기간 yy.MM.dd ~ yy.MM.dd}</td>
    <td>{조회수}</td>
  </tr>

상세 URL 패턴
-------------
/kocca/pims/view.do?intcNo={intcNo}&menuNo=204104&...

intcNo 예: "326D00091006" (10자리 영숫자)
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Optional

from selectolax.parser import HTMLParser

from ._base import (
    Announcement,
    FetchError,
    NormalizeError,
    Source,
    parse_kr_date,
    parse_range_kr_date,
)

logger = logging.getLogger("founder_gov_radar.sources.kocca")

LIST_URL = "https://www.kocca.kr/kocca/pims/list.do"
VIEW_URL_PREFIX = "https://www.kocca.kr/kocca/pims/view.do"
MENU_NO = 204104  # 지원사업 메뉴


class KoccaSource(Source):
    code = "kocca"
    label = "한국콘텐츠진흥원 KOCCA"
    homepage = "https://www.kocca.kr"
    auth = "none"
    priority = 1.05  # 생애주기 L3 부스트
    min_interval = 2.0

    MAX_PAGES = 10  # 안전장치 (실측 활성 공고 17건 → 2 페이지)

    def crawl(self, since: Optional[date] = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page in range(1, self.MAX_PAGES + 1):
            r = self.fetch(LIST_URL, params={"menuNo": MENU_NO, "pageIndex": page})
            if r.status_code != 200:
                raise FetchError(self.code, f"list page {page} → {r.status_code}")
            chunk = self._parse_list_page(r.text, page)
            if not chunk:
                logger.info("[kocca] page %d empty, stopping", page)
                break
            items.extend(chunk)
            logger.debug("[kocca] page %d: %d items (cumulative %d)", page, len(chunk), len(items))
        logger.info("[kocca] crawl 완료: %d items", len(items))
        return items

    def _parse_list_page(self, html: str, page: int) -> list[dict[str, Any]]:
        tree = HTMLParser(html)
        items = []
        for row in tree.css("table tbody tr"):
            link = row.css_first("a[href*='pims/view.do']")
            if not link:
                continue  # empty placeholder row
            href = link.attributes.get("href", "")
            m = re.search(r"intcNo=([A-Za-z0-9]+)", href)
            if not m:
                continue
            intcNo = m.group(1)
            cells = row.css("td")
            if len(cells) < 5:
                continue
            items.append({
                "intcNo": intcNo,
                "type": cells[0].text(strip=True),     # "모집공모" / "자유공모"
                "title": cells[1].text(strip=True),
                "registDate": cells[2].text(strip=True),  # "yy.MM.dd"
                "period": cells[3].text(strip=True),      # "yy.MM.dd ~ yy.MM.dd"
                "views": cells[4].text(strip=True),
                "href": href,
                "_source_page": page,
            })
        return items

    def normalize(self, raw: dict[str, Any]) -> Announcement:
        intcNo = raw.get("intcNo")
        if not intcNo:
            raise NormalizeError("kocca raw missing intcNo")

        title = (raw.get("title") or "").strip()
        if not title:
            raise NormalizeError(f"kocca {intcNo}: empty title")

        # 등록일 "26.04.23" → "2026-04-23"
        published_at = self._parse_short_kr_date(raw.get("registDate"))

        # 접수기간 "26.04.23 ~ 26.05.14"
        _, deadline = self._parse_short_kr_range(raw.get("period"))

        href = raw.get("href", "")
        url = href if href.startswith("http") else f"https://www.kocca.kr{href}"

        return Announcement(
            schema_version=5,
            source=self.code,
            source_label=self.label,
            id=self.build_announcement_id(intcNo),
            title=title,
            agency="한국콘텐츠진흥원",
            url=url,
            deadline=deadline,
            published_at=published_at,
            structured=raw,
        )

    # -- helpers --

    @staticmethod
    def _parse_short_kr_date(s: Optional[str]) -> Optional[str]:
        """'26.04.23' → '2026-04-23' (yy는 20yy로 확장)."""
        if not s:
            return None
        m = re.match(r"(\d{2})\.(\d{1,2})\.(\d{1,2})", s.strip())
        if not m:
            return parse_kr_date(s)
        yy, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # 20yy 가정 (정부 공고라 2020+ 안전)
        year = 2000 + yy if yy < 90 else 1900 + yy
        return f"{year:04d}-{mo:02d}-{d:02d}"

    @classmethod
    def _parse_short_kr_range(cls, s: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        """'26.04.23 ~ 26.05.14' → (start, end)."""
        if not s:
            return None, None
        parts = [p.strip() for p in s.split("~")]
        if len(parts) != 2:
            return None, cls._parse_short_kr_date(parts[0]) if parts else None
        return cls._parse_short_kr_date(parts[0]), cls._parse_short_kr_date(parts[1])
