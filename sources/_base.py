"""Source abstract base class + shared utilities for founder-gov-radar v10.

모든 정부·공공기관 source 어댑터가 이 모듈의 Source를 상속한다.
새 source 추가 시 crawl()·normalize()만 구현하면 나머지(재시도·로깅·
heath check·timeout)는 base가 처리한다.

원칙
----
* **순수 Python 3.10+** — LLM 호출 없음. classify_v10에서만 LLM 쓴다.
* **네트워크 요청은 httpx** (동기). 비동기는 source 수 늘어나면 검토.
* **robots.txt를 존중**한다. `_base.check_robots()` 훅이 있으니 구현체에서 호출.
* **User-Agent에 연락처 포함** — 관리자가 문의할 수 있도록.
* **rate limit**: 기본 10req/min. `min_interval_sec` 로 오버라이드.

스키마 버전
----------
Announcement.schema_version = 5 (v10부터). v4→v5 마이그레이션은
`normalize.migrate_v4_to_v5()` 가 담당.
"""
from __future__ import annotations

import abc
import json
import logging
import random
import time
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Literal, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("founder_gov_radar.sources")

# ---------------------------------------------------------------------------
# 공통 상수
# ---------------------------------------------------------------------------

USER_AGENT = "founder-gov-radar/0.10 (heoparang@gmail.com; sinhon.life)"
DEFAULT_TIMEOUT_SEC = 30.0
DEFAULT_MIN_INTERVAL_SEC = 6.0  # 10 req/min (60 / 10)
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SEC = 2.0

SCHEMA_VERSION = 5

AuthKind = Literal["none", "serviceKey", "login", "api_key", "session_cookie"]

# ---------------------------------------------------------------------------
# 예외
# ---------------------------------------------------------------------------


class FetchError(RuntimeError):
    """Source 네트워크/파싱 실패. crawl_all 은 이 에러를 잡아서 source별 격리."""

    def __init__(self, source_code: str, reason: str, *, retriable: bool = False) -> None:
        super().__init__(f"[{source_code}] {reason}")
        self.source_code = source_code
        self.reason = reason
        self.retriable = retriable


class NormalizeError(ValueError):
    """원본 → 공통 스키마 변환 실패."""


# ---------------------------------------------------------------------------
# 공통 스키마 (Announcement)
# ---------------------------------------------------------------------------


@dataclass
class AnnualRecurringMatch:
    """Step 4.5 ANNUAL_RECURRING_CHECK 결과."""

    matched_entry_id: str
    title_pattern: str
    confidence: Literal["high", "med", "low"]


@dataclass
class Announcement:
    """공통 공고 스키마 v5. 모든 source의 normalize() 가 이 dataclass를 반환."""

    schema_version: int
    source: str  # "bizinfo", "k_startup", ...
    source_label: str
    id: str  # "{source}_{pbancSn|slug}"
    title: str
    agency: str
    url: str
    deadline: Optional[str]  # "YYYY-MM-DD" or None (상시)
    published_at: Optional[str]

    # 매칭/티어는 classify_v10에서 채움. crawl·normalize 단계에선 None.
    pbancSn: Optional[str] = None
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    region: Optional[str] = None
    target_stage: list[str] = field(default_factory=list)
    budget_max_manwon: Optional[int] = None

    tier: Optional[str] = None
    best_entity: Optional[str] = None
    best_tier: Optional[str] = None
    entities: dict[str, Any] = field(default_factory=dict)
    domain: dict[str, Any] = field(default_factory=dict)
    annual_recurring: Optional[AnnualRecurringMatch] = None
    nogo_match: Optional[dict[str, Any]] = None
    deep_verdict: Optional[dict[str, Any]] = None
    rationale_short: Optional[str] = None

    # 원본 응답은 그대로 보존(감사용)
    structured: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.annual_recurring is not None:
            d["annual_recurring"] = asdict(self.annual_recurring)
        return d


@dataclass
class SourceHealthStatus:
    source_code: str
    ok: bool
    checked_at: str  # ISO8601
    latency_ms: Optional[int]
    detail: str


# ---------------------------------------------------------------------------
# Source 추상 클래스
# ---------------------------------------------------------------------------


class Source(abc.ABC):
    """모든 source 어댑터의 기본 클래스.

    구현체가 세팅해야 할 클래스 속성
    --------------------------------
    * `code`          — "bizinfo" (고유, 영소문자+언더스코어)
    * `label`         — "중소벤처기업부 BIZINFO" (대시보드 표시용)
    * `homepage`      — "https://www.bizinfo.go.kr"
    * `auth`          — AuthKind
    * `priority`      — 0.80 ~ 1.10 (profile.md::SOURCE_PRIORITY 와 일치)
    * `min_interval`  — 요청 간 최소 간격(초). 기본 6.0.

    구현체가 반드시 구현해야 할 메서드
    ---------------------------------
    * `crawl(since)`      — 원본 응답 리스트 반환
    * `normalize(raw)`    — 단일 원본 → Announcement

    선택적으로 오버라이드
    --------------------
    * `detail(ann)`       — 상세 페이지 추가 페치(RSS처럼 목록이 얕을 때)
    * `health_check()`    — 커스텀 헬스체크 로직
    """

    code: str = ""
    label: str = ""
    homepage: str = ""
    auth: AuthKind = "none"
    priority: float = 1.00
    min_interval: float = DEFAULT_MIN_INTERVAL_SEC

    def __init__(self, *, http_client: Optional[httpx.Client] = None) -> None:
        if not self.code:
            raise ValueError(f"{self.__class__.__name__}.code is required")
        self._client = http_client or self._default_client()
        self._last_request_ts: float = 0.0

    # ---- 필수 훅 ----

    @abc.abstractmethod
    def crawl(self, since: Optional[date] = None) -> list[dict[str, Any]]:
        """원본 응답을 리스트로 반환. normalize는 별도 호출."""

    @abc.abstractmethod
    def normalize(self, raw: dict[str, Any]) -> Announcement:
        """원본 1건 → Announcement."""

    # ---- 선택 훅 ----

    def detail(self, ann: Announcement) -> Announcement:
        """상세 페이지에서 추가 정보 채움. 기본은 no-op."""
        return ann

    def health_check(self) -> SourceHealthStatus:
        """홈페이지 200 OK + 응답 시간. 구현체에서 필요 시 오버라이드."""
        t0 = time.monotonic()
        try:
            r = self._client.get(self.homepage, timeout=DEFAULT_TIMEOUT_SEC)
            ok = r.status_code == 200
            detail = f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            return SourceHealthStatus(
                source_code=self.code,
                ok=False,
                checked_at=datetime.utcnow().isoformat() + "Z",
                latency_ms=None,
                detail=f"{type(exc).__name__}: {exc}",
            )
        latency_ms = int((time.monotonic() - t0) * 1000)
        return SourceHealthStatus(
            source_code=self.code,
            ok=ok,
            checked_at=datetime.utcnow().isoformat() + "Z",
            latency_ms=latency_ms,
            detail=detail,
        )

    # ---- 공통 유틸: HTTP ----

    def _default_client(self) -> httpx.Client:
        return httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"},
            timeout=DEFAULT_TIMEOUT_SEC,
            follow_redirects=True,
        )

    def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        params: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        retries: int = DEFAULT_RETRY_ATTEMPTS,
    ) -> httpx.Response:
        """재시도 + rate limit 자동. 4xx는 즉시 반환(재시도 X)."""
        self._throttle()
        last_exc: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                r = self._client.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    headers=headers,
                )
                if 500 <= r.status_code < 600:
                    raise FetchError(
                        self.code,
                        f"{method} {url} → {r.status_code} (attempt {attempt})",
                        retriable=True,
                    )
                return r
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                logger.warning("[%s] fetch retry %d/%d: %s", self.code, attempt, retries, exc)
                time.sleep(DEFAULT_RETRY_BACKOFF_SEC * attempt + random.random())
            except FetchError as exc:
                last_exc = exc
                if not exc.retriable:
                    raise
                time.sleep(DEFAULT_RETRY_BACKOFF_SEC * attempt + random.random())
        raise FetchError(self.code, f"fetch failed after {retries} retries: {last_exc}")

    def _throttle(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request_ts
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_ts = time.monotonic()

    # ---- 공통 유틸: URL ----

    @staticmethod
    def same_host(url: str, homepage: str) -> bool:
        return urlparse(url).netloc == urlparse(homepage).netloc

    def build_announcement_id(self, raw_id: str | int) -> str:
        return f"{self.code}_{raw_id}"

    # ---- 공통 유틸: 저장 ----

    def save_raw(self, raws: Iterable[dict[str, Any]], out_dir: Path) -> Path:
        """source별 크롤 결과를 JSON으로 저장. crawl_all 이 호출."""
        out_dir.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        out_path = out_dir / f"{self.code}_{today}.json"
        payload = {
            "source": self.code,
            "source_label": self.label,
            "crawled_at": datetime.utcnow().isoformat() + "Z",
            "items": list(raws),
        }
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out_path

    # ---- repr ----

    def __repr__(self) -> str:
        return f"<Source code={self.code!r} label={self.label!r} auth={self.auth!r}>"


# ---------------------------------------------------------------------------
# 공통 헬퍼 (날짜 파싱 등)
# ---------------------------------------------------------------------------


def parse_kr_date(s: Optional[str]) -> Optional[str]:
    """'2026.05.31', '2026-05-31', '2026/05/31', '2026년 5월 31일' → 'YYYY-MM-DD'."""
    if not s:
        return None
    s = s.strip()
    for sep in (".", "/", "년", "월", "일"):
        s = s.replace(sep, "-")
    s = s.replace(" ", "").rstrip("-")
    parts = [p for p in s.split("-") if p]
    if len(parts) < 3:
        return None
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        return f"{y:04d}-{m:02d}-{d:02d}"
    except ValueError:
        return None


def parse_range_kr_date(s: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """'2026.04.01 ~ 2026.05.31' → (start, end)."""
    if not s:
        return None, None
    for sep in ("~", "-", "~", "–", "—"):
        if sep in s and s.count(sep) >= 1:
            left, _, right = s.partition(sep)
            return parse_kr_date(left), parse_kr_date(right)
    # 단일 날짜면 end로 간주
    return None, parse_kr_date(s)


def strip_html(text: str) -> str:
    """태그·연속 공백 제거."""
    import re

    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
