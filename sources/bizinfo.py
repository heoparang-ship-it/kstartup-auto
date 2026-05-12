"""BIZINFO (중소벤처기업부 기업마당) 어댑터 — 실측 기반 (2026-04-24).

공공데이터포털 API
-----------------
* 등록 URL: https://www.data.go.kr/data/15081808/openapi.do
* 엔드포인트: https://apis.data.go.kr/1421000/bizinfo/pblancBsnsService
* 응답 포맷: JSON (or XML) — 기본 JSON 사용
* serviceKey: data.go.kr 계정 범용 키
* 일일 트래픽: 10,000 (개발계정 기본)
* perPage 상한: 실측 2000+ 가능. totalCount=1363 (2026-04-24 기준) 전체를 한 번에 받을 수 있음
* rate limit: 연속 burst 시 401. **요청 간 최소 1.5초 권장**

응답 구조 (실측)
---------------
{
  "response": {
    "header": { "resultCode": "00", "resultMsg": "NORMAL_SERVICE" },
    "body": {
      "totalCount": 1363,
      "numOfRows": 10,
      "pageNo": 1,
      "items": { "item": [ {...}, {...} ] }     # item이 list 또는 단건 dict
    }
  }
}

단건 필드 (20개)
---------------
pblancId            : "PBLN_000000000121282"  (고유 ID)
pblancNm            : "2026년 온라인수출 ..."  (제목)
pblancUrl           : "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=..."
jrsdInsttNm         : "중소벤처기업부"        (주관기관)
excInsttNm          : "중소벤처기업진흥공단"  (시행기관)
bsnsSumryCn         : "<p>중소기업 온라인수출 ...</p>" (사업개요 — HTML 포함)
pldirSportRealmLclasCodeNm : "수출"          (분야)
creatPnttm          : "2026-04-24 15:39:08"   (등록일시)
reqstBeginEndDe     : "2026-04-24 ~ 2026-05-15" (접수기간)
updtPnttm           : "2026-04-24 15:49:59"   (수정일시)
trgetNm             : "중소기업"              (지원대상)
inqireCo            : 155                     (조회수)
flpthNm             : 첨부파일1 URL
fileNm              : 첨부파일1 파일명
printFlpthNm        : 인쇄용 URL
printFileNm         : 인쇄용 파일명
hashtags            : "수출,서울,부산,...,중소벤처기업부,..." (쉼표 구분)
reqstMthPapersCn    : "온라인 접수 (고비즈코리아)" (접수방법)
refrncNm            : 문의처
rceptEngnHmpgUrl    : 접수 홈페이지 URL
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

from ._base import (
    Announcement,
    FetchError,
    NormalizeError,
    Source,
    parse_kr_date,
    parse_range_kr_date,
    strip_html,
)

logger = logging.getLogger("founder_gov_radar.sources.bizinfo")

# bizinfo.go.kr 자체 API (crtfcKey 인증)
# 응답: {"jsonArray": [...]}, 각 item에 totCnt 동봉
API_ENDPOINT = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
DETAIL_URL_BASE = "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do"


def _load_env(env_path: Path) -> None:
    """단순 .env 파서 (외부 의존 피함)."""
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


# 모듈 import 시 키 파일 자동 로드 (있으면)
# 우선순위:
#   1) kstartup-auto/.api_keys/bizinfo.env  (이 repo 안)
#   2) ../.api_keys/bizinfo.env             (legacy, founder-gov-radar 위치)
#   3) GH Actions 의 BIZINFO_SERVICE_KEY env var (그대로 통과)
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _env_path in (
    _REPO_ROOT / ".api_keys" / "bizinfo.env",
    _REPO_ROOT.parent / ".api_keys" / "bizinfo.env",
):
    _load_env(_env_path)


class BizinfoSource(Source):
    code = "bizinfo"
    label = "중소벤처기업부 BIZINFO (기업마당)"
    homepage = "https://www.bizinfo.go.kr"
    auth = "api_key"
    priority = 1.00
    # 실측 결과 burst 시 응답 지연/오류 가능. 보수적으로 1.8초 간격.
    min_interval = 1.8

    # bizinfo.go.kr 자체 API: 한 페이지 최대 500개 (안내문 명시)
    PAGE_SIZE = 500
    MAX_PAGES = 20  # 500 × 20 = 10,000건 — 현실적 상한

    def __init__(self, *, service_key: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # 환경변수 호환: BIZINFO_SERVICE_KEY (우선) / BIZINFO_CRTFC_KEY / DATA_GO_KR_KEY
        self._service_key = (
            service_key
            or os.environ.get("BIZINFO_SERVICE_KEY")
            or os.environ.get("BIZINFO_CRTFC_KEY")
            or os.environ.get("DATA_GO_KR_KEY")
        )
        if not self._service_key:
            logger.warning("[bizinfo] crtfcKey not set — crawl()은 빈 list 반환 (graceful skip)")

    # --------------------------------------------------------------------
    # crawl()
    # --------------------------------------------------------------------

    def crawl(self, since: Optional[date] = None) -> list[dict[str, Any]]:
        # graceful skip: 키 없으면 빈 list (시스템 안 깨지게)
        if not self._service_key:
            logger.info("[bizinfo] skip — crtfcKey 미설정")
            return []

        # 첫 페이지 호출 → totCnt 추출 (각 item에 들어있음)
        first = self._fetch_page(1, self.PAGE_SIZE)
        first_items = self._extract_items(first)
        if not first_items:
            logger.info("[bizinfo] empty response on page 1")
            return []
        total = int(first_items[0].get("totCnt") or 0)
        logger.info("[bizinfo] totCnt=%d (page1=%d items)", total, len(first_items))

        collected: list[dict[str, Any]] = list(first_items)
        page = 2
        while len(collected) < total and page <= self.MAX_PAGES:
            data = self._fetch_page(page, self.PAGE_SIZE)
            items = self._extract_items(data)
            if not items:
                break
            collected.extend(items)
            logger.debug("[bizinfo] page=%d +%d cumulative=%d/%d", page, len(items), len(collected), total)
            page += 1

        logger.info("[bizinfo] crawl 완료: %d items (target %d)", len(collected), total)
        return collected

    def _fetch_page(self, page_no: int, per_page: int) -> dict[str, Any]:
        # bizinfo.go.kr 자체 API 파라미터: crtfcKey, dataType, searchCnt, pageUnit, pageIndex
        params = {
            "crtfcKey": self._service_key,
            "dataType": "json",
            "searchCnt": per_page,
            "pageUnit": per_page,
            "pageIndex": page_no,
        }
        r = self.fetch(API_ENDPOINT, params=params)
        if r.status_code != 200:
            raise FetchError(
                self.code,
                f"bizinfoApi returned {r.status_code} — {r.text[:120]}",
                retriable=r.status_code in (401, 429, 500, 502, 503),
            )
        try:
            return r.json()
        except ValueError as exc:
            raise FetchError(self.code, f"invalid JSON: {exc} body[:200]={r.text[:200]!r}") from exc

    @staticmethod
    def _extract_items(data: dict[str, Any]) -> list[dict[str, Any]]:
        """bizinfo.go.kr 자체 API 응답 → item list.

        실측 응답: {"jsonArray": [...]}
        """
        arr = data.get("jsonArray")
        if isinstance(arr, list):
            return arr
        return []

    # --------------------------------------------------------------------
    # normalize()
    # --------------------------------------------------------------------

    def normalize(self, raw: dict[str, Any]) -> Announcement:
        pblancId = raw.get("pblancId")
        if not pblancId:
            raise NormalizeError("BIZINFO raw missing pblancId")

        title = (raw.get("pblancNm") or "").strip()
        # 주관기관 + 시행기관 동시 매칭 보장 위해 결합
        jrsd = (raw.get("jrsdInsttNm") or "").strip()
        exc = (raw.get("excInsttNm") or "").strip()
        agency = jrsd if jrsd == exc else f"{jrsd} / {exc}".strip(" /")

        # 접수기간 "YYYY-MM-DD ~ YYYY-MM-DD"
        _, deadline = parse_range_kr_date(raw.get("reqstBeginEndDe"))

        # 등록일시 "YYYY-MM-DD HH:MM:SS"
        published_at = self._parse_dt_date(raw.get("creatPnttm"))

        # URL — pblancUrl 가 있으면 우선, 없으면 빌드
        url = raw.get("pblancUrl") or f"{DETAIL_URL_BASE}?pblancId={pblancId}"

        # region — hashtags 에서 지역명 추출
        region = self._extract_region(raw.get("hashtags", ""))

        # 대상 단계 (예비창업/초기창업/소상공인/...)
        target_stage = self._extract_stages(raw)

        # 예산 (bsnsSumryCn 에서 가장 큰 금액 파싱)
        budget_max_manwon = self._extract_budget(raw.get("bsnsSumryCn", "") + " " + title)

        return Announcement(
            schema_version=5,
            source=self.code,
            source_label=self.label,
            id=self.build_announcement_id(pblancId),
            pbancSn=None,
            title=title,
            agency=agency,
            url=url,
            deadline=deadline,
            published_at=published_at,
            region=region,
            target_stage=target_stage,
            budget_max_manwon=budget_max_manwon,
            structured=raw,
        )

    # --------------------------------------------------------------------
    # 필드 파서 유틸
    # --------------------------------------------------------------------

    @staticmethod
    def _parse_dt_date(s: Optional[str]) -> Optional[str]:
        """'2026-04-24 15:39:08' → '2026-04-24'."""
        if not s:
            return None
        return parse_kr_date(s.split(" ")[0])

    @staticmethod
    def _extract_region(hashtags: str) -> Optional[str]:
        """hashtags 에서 지역명 추출. 17개 광역 + '전국'."""
        if not hashtags:
            return None
        tokens = [t.strip() for t in hashtags.split(",")]
        regions_17 = [
            "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
            "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
        ]
        hits = [r for r in regions_17 if r in tokens]
        if not hits:
            return None
        if len(hits) >= 16:
            return "전국"
        return ",".join(hits)

    @staticmethod
    def _extract_stages(raw: dict[str, Any]) -> list[str]:
        text = (
            (raw.get("bsnsSumryCn") or "")
            + " " + (raw.get("pblancNm") or "")
            + " " + (raw.get("trgetNm") or "")
            + " " + (raw.get("hashtags") or "")
        )
        stages = []
        if "예비창업" in text:
            stages.append("예비창업")
        if re.search(r"초기\s*창업|창업\s*3년\s*이내|업력\s*3년", text):
            stages.append("초기창업")
        if re.search(r"창업\s*7년|도약", text):
            stages.append("창업7년이내")
        if "소상공인" in text:
            stages.append("소상공인")
        if re.search(r"청년\s*창업|청년창업", text):
            stages.append("청년창업")
        if re.search(r"여성\s*창업|여성기업", text):
            stages.append("여성창업")
        return stages

    @staticmethod
    def _extract_budget(text: str) -> Optional[int]:
        """공고 텍스트에서 '최대 N억/N천만원' 등 예산 단위 파싱 (만원 단위 반환)."""
        if not text:
            return None
        cleaned = strip_html(text)
        # "최대 1억 이내", "1억 5천만원", "3,000만원" 등
        candidates: list[int] = []
        for m in re.finditer(r"(?:최대\s*)?([\d,]+)\s*(억|천만|백만|만)\s*원", cleaned):
            n = int(m.group(1).replace(",", ""))
            unit = m.group(2)
            mult = {"억": 10000, "천만": 1000, "백만": 100, "만": 1}[unit]
            candidates.append(n * mult)
        if not candidates:
            return None
        return max(candidates)
