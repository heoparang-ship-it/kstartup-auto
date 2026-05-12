#!/usr/bin/env python3
"""
K-Startup 공고 자동 업데이트 오케스트레이터 v5 (founder-gov-radar)
크롤 → 규칙 분류 → 만료 삭제 → upsert → 🟢🟡 원문 fetch 저장

v5 변경점 (Haiku 제거):
- deep_summary(Haiku) 완전 제거 — API 키 불필요
- 🟢🟡 항목에 한해 K-Startup 원문 fetch → raw_content 저장
- 분석은 Cowork 세션에서 on-demand (원문 읽어서 즉시 판단)
- --skip-crawl: 크롤 스킵, pool 재분류만 수행
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

from crawl import crawl
from classify import classify, TODAY
from crawl_itp import crawl as crawl_itp, classify_itp

# v6 (2026-05-12): BIZINFO + KOCCA 어댑터 통합 (자동 갱신 정상화)
# 어댑터 import는 try-guarded — 의존성 누락 시 K-Startup/ITP는 계속 동작
try:
    from sources.bizinfo import BizinfoSource
    from sources.kocca import KoccaSource
    EXTERNAL_SOURCES_AVAILABLE = True
except ImportError as _e:
    print(f"[external] sources/ 어댑터 import 실패 — BIZINFO/KOCCA 스킵: {_e}",
          file=__import__("sys").stderr)
    BizinfoSource = KoccaSource = None
    EXTERNAL_SOURCES_AVAILABLE = False

KST = timezone(timedelta(hours=9))
POOL_FILE = "recommendations.json"
STALE_DAYS = 14
HISTORY_MAX_DAYS = 30

# 원문 fetch 설정
FETCH_TIERS = {"green", "yellow"}
FETCH_CONTENT_MAX_CHARS = 2500
FETCH_TIMEOUT_S = 12
FETCH_MAX_PER_RUN = 20   # 신규 항목 중 최대 fetch 건수 (Actions 시간 제한 대비)


# ── 원문 fetch ────────────────────────────────────────────────
def fetch_announcement_content(pbancSn: str) -> str:
    """K-Startup 공고 원문 fetch. 성공 시 텍스트, 실패 시 빈 문자열."""
    url = (
        f"https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"
        f"?schM=view&pbancSn={pbancSn}"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT_S)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
            tag.decompose()
        content = (
            soup.find("div", class_="app_notice_details-wrap")
            or soup.find("div", class_="information_list-wrap")
            or soup.find("div", class_="board-view-content")
            or soup.find("div", id="content")
            or soup.find("article")
            or soup.find("main")
        )
        text = (content or soup).get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:FETCH_CONTENT_MAX_CHARS]
    except Exception as e:
        print(f"[fetch] {pbancSn} 실패: {e}", file=sys.stderr)
        return ""


def enrich_raw_content(items: list):
    """🟢🟡 신규 항목(raw_content 없음)에 한해 원문 fetch 후 저장.
    ITP 항목(pbancSn=itp_*)은 K-Startup URL 패턴 미적용이라 제외."""
    targets = [
        it for it in items
        if it.get("tier") in FETCH_TIERS
        and not it.get("raw_content")
        and not str(it.get("pbancSn", "")).startswith("itp_")
    ]
    if not targets:
        print("[fetch] raw_content 신규 대상 없음", file=sys.stderr)
        return

    # 마감 임박 순 정렬
    targets.sort(key=lambda x: x.get("deadline") or "9999-99-99")
    to_fetch = targets[:FETCH_MAX_PER_RUN]

    print(f"[fetch] 원문 fetch 대상 {len(to_fetch)}건 (전체 미수집 {len(targets)}건)", file=sys.stderr)
    succ = 0
    for idx, item in enumerate(to_fetch, 1):
        sn = item.get("pbancSn", "")
        content = fetch_announcement_content(sn)
        if content:
            item["raw_content"] = content
            item["raw_fetched_at"] = TODAY
            succ += 1
        print(
            f"[fetch] {idx}/{len(to_fetch)} {'OK' if content else 'FAIL'} "
            f"{sn} ({len(content)}자) {item.get('title','')[:25]}...",
            file=sys.stderr,
        )
        time.sleep(0.5)

    print(f"[fetch] 완료 {succ}/{len(to_fetch)}건", file=sys.stderr)


# ── 외부 소스 (BIZINFO / KOCCA) 통합 ──────────────────────────
# 2026-05-12: founder-gov-radar의 어댑터를 sources/ 로 옮기고 매일 자동 갱신에 통합.
# ITP가 classify_itp 가지듯, BIZINFO/KOCCA는 _classify_external 사용.
# 작은 룰 기반: region(인천/전국) + 콘텐츠/창업 키워드 + 마감일.

INCHEON_KEYWORDS = ("인천", "Incheon", "INCHEON")
NATIONAL_KEYWORDS = ("전국", "대한민국")
CONTENT_KEYWORDS = ("콘텐츠", "콘텐트", "미디어", "영상", "유튜브", "크리에이터",
                    "방송", "OTT", "1인 미디어", "1인미디어")
STARTUP_KEYWORDS = ("창업", "예비창업", "초기창업", "스타트업", "벤처", "사업화",
                    "BM", "MVP", "데모데이")
SW_KEYWORDS = ("소프트웨어", "SW", "AI", "인공지능", "데이터", "플랫폼", "앱",
               "웹서비스", "PWA")


def _classify_external(ann) -> tuple[str, dict]:
    """BIZINFO/KOCCA Announcement → (tier, evidence). 단순 룰 기반.

    green: 인천 매칭 + 창업/콘텐츠/SW 중 하나
    yellow: 전국/콘텐츠/SW 중 하나 (인천 아님)
    orange: 그 외
    """
    title = (ann.title or "")
    agency = (ann.agency or "")
    structured = ann.structured or {}
    text = title + " " + agency
    # bsnsSumryCn (BIZINFO) 또는 raw HTML 일부도 포함
    summary = str(structured.get("bsnsSumryCn") or structured.get("hashtags") or "")[:1500]
    text_full = text + " " + summary

    region = (ann.region or "").strip() or "?"
    is_incheon = (
        "인천" in region or
        any(k in agency for k in INCHEON_KEYWORDS) or
        any(k in title for k in INCHEON_KEYWORDS)
    )
    is_national = (
        "전국" in region or
        any(k in title for k in NATIONAL_KEYWORDS)
    )
    has_content = any(k in text_full for k in CONTENT_KEYWORDS)
    has_startup = any(k in text_full for k in STARTUP_KEYWORDS)
    has_sw = any(k in text_full for k in SW_KEYWORDS)

    # 다른 광역지역 단독이면 강제 orange (인천/전국 둘 다 아니면)
    other_only = False
    other_regions = ["부산", "대구", "광주", "대전", "울산", "세종", "경기",
                     "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]
    if not is_incheon and not is_national:
        if any(r in region for r in other_regions) or any(r in agency for r in other_regions):
            other_only = True

    # tier 결정
    if is_incheon and (has_content or has_startup or has_sw):
        tier = "green"
        reason = "인천 매칭 + " + (
            "콘텐츠" if has_content else "창업" if has_startup else "SW"
        )
    elif is_incheon:
        tier = "yellow"
        reason = "인천 매칭 (도메인 모호)"
    elif is_national and (has_content or has_startup or has_sw):
        tier = "yellow"
        reason = "전국 + " + (
            "콘텐츠" if has_content else "창업" if has_startup else "SW"
        )
    elif other_only:
        tier = "orange"
        reason = f"비수도권 단독 ({region})"
    else:
        tier = "orange"
        reason = "도메인/지역 매칭 약함"

    evidence = {
        "summary_reason": reason,
        "category_hints": [ann.source] + ([region] if region != "?" else []),
        "rule_checks": {
            "recruiting": {"pass": True, "value": "True", "detail": "어댑터 통과"},
            "deadline": {
                "pass": bool(ann.deadline),
                "value": ann.deadline or "",
                "detail": "어댑터 normalize",
            },
            "region": {"pass": is_incheon or is_national, "value": region,
                       "detail": "agency·title·region 종합"},
        },
        "axis_scores": {
            "region": "green" if is_incheon else ("yellow" if is_national else "orange"),
            "stage": "green" if has_startup else "yellow",
            "industry": "green" if (has_content or has_sw) else "yellow",
            "nature": "yellow",
            "qualification": "yellow",
        },
        "exclusion_flags": [],
        "audit_flags": [],
        "tier_logic": f"{ann.source} 룰 → {tier}",
        "classify_version": "v8.3-external",
    }
    return tier, evidence


def _ann_to_pool_item(ann, tier: str, evidence: dict) -> dict:
    """Announcement → update.py 풀 항목 dict."""
    return {
        "pbancSn": ann.id,            # dedup 키로 사용 (bizinfo_PBLN_..., kocca_intcNo)
        "id": ann.id,                 # 기존 풀 호환 (source=bizinfo 항목들이 이 필드 사용)
        "source": ann.source,
        "source_label": ann.source_label,
        "title": ann.title,
        "agency": ann.agency,
        "url": ann.url,
        "deadline": ann.deadline or "",
        "tier": tier,
        "note": evidence.get("summary_reason", ""),
        "classify_evidence": evidence,
        "first_seen": TODAY,
        "last_seen": TODAY,
        "structured": ann.structured or {},
    }


def crawl_external_sources(known_keys: set) -> list[dict]:
    """sources/ 의 BIZINFO + KOCCA 어댑터 호출. try/except per source.

    Returns: [(tier, evidence, pool_item) ...] 형태가 아니라
             dict 리스트 (update.py 처리부에서 dedup·classify·merge).
    """
    if not EXTERNAL_SOURCES_AVAILABLE:
        print("[external] sources/ 미사용 — 스킵", file=sys.stderr)
        return []

    all_items: list[dict] = []
    source_classes = [
        ("kocca", KoccaSource),    # 인증 불필요 — 먼저 (안정)
        ("bizinfo", BizinfoSource), # 키 필요 — 없으면 graceful skip (빈 list)
    ]
    for code, cls in source_classes:
        try:
            src = cls()
            raws = src.crawl()
            print(f"[external/{code}] crawl OK: {len(raws)}건", file=sys.stderr)
            success = 0
            for raw in raws:
                try:
                    ann = src.normalize(raw)
                except Exception as e:
                    print(f"[external/{code}] normalize 실패 (skip): {e}", file=sys.stderr)
                    continue
                tier, evidence = _classify_external(ann)
                pool_item = _ann_to_pool_item(ann, tier, evidence)
                all_items.append(pool_item)
                success += 1
            print(f"[external/{code}] normalize+classify OK: {success}건", file=sys.stderr)
        except Exception as e:
            print(f"[external/{code}] FAIL (스킵): {e}", file=sys.stderr)
            # 한 소스 깨져도 다음 소스 + 기존 K-Startup/ITP 계속 진행
            continue

    print(f"[external] 합계: {len(all_items)}건", file=sys.stderr)
    return all_items


# ── pool 관리 ─────────────────────────────────────────────────
def load_pool() -> dict:
    try:
        with open(POOL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("schema_version") not in (2, 3, 4, 5):
            raise ValueError("schema mismatch")
        data.setdefault("history", [])
        return data
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {
            "schema_version": 5,
            "last_updated": TODAY,
            "updated_at_kst": "",
            "history": [],
            "items": [],
            "red_count_today": 0,
        }


def save_pool(pool: dict, now_kst: datetime):
    pool["schema_version"] = 5
    pool["last_updated"] = TODAY
    pool["updated_at_kst"] = now_kst.strftime("%Y-%m-%dT%H:%M:%S+09:00")
    with open(POOL_FILE, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)
    print(f"[save] {POOL_FILE} 저장 완료 ({len(pool['items'])}건)", file=sys.stderr)


def expire_items(items: list) -> tuple:
    stale_cutoff = (datetime.now(KST) - timedelta(days=STALE_DAYS)).strftime("%Y-%m-%d")
    kept, expired_titles = [], []
    for item in items:
        dl = item.get("deadline", "")
        ls = item.get("last_seen", "")
        if dl and dl < TODAY:
            expired_titles.append(item.get("title", ""))
        elif ls and ls < stale_cutoff:
            expired_titles.append(item.get("title", "") + " (stale)")
        else:
            kept.append(item)
    return kept, expired_titles


def prune_history(history: list, now_kst: datetime) -> list:
    cutoff = (now_kst - timedelta(days=HISTORY_MAX_DAYS)).strftime("%Y-%m-%d")
    return [h for h in history if h.get("date", "") >= cutoff]


# ── 메인 ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-crawl", action="store_true",
                        help="크롤 스킵, pool 재분류 + 원문 fetch만 수행")
    args = parser.parse_args()

    now_kst = datetime.now(KST)
    pool = load_pool()
    existing_items = pool.get("items", [])
    print(f"[load] 기존 풀: {len(existing_items)}건", file=sys.stderr)

    if args.skip_crawl:
        print("[skip-crawl] 크롤 스킵. pool 전체 재분류만 수행", file=sys.stderr)
        kept_items = []
        red_count = 0
        reclassified = 0
        for item in existing_items:
            prev_tier = item.get("tier")
            if str(item.get("pbancSn", "")).startswith("itp_"):
                tier, evidence = classify_itp(item)
            else:
                tier, evidence = classify(item)
            item["tier"] = tier
            item["note"] = evidence.get("summary_reason", "")
            item["classify_evidence"] = evidence
            if tier == "red":
                red_count += 1
                continue
            if prev_tier != tier:
                reclassified += 1
                # 티어 바뀌면 raw_content 재수집
                if tier in FETCH_TIERS and prev_tier not in FETCH_TIERS:
                    item.pop("raw_content", None)
                    item.pop("raw_fetched_at", None)
            kept_items.append(item)
        print(f"[reclassify] {reclassified}건 변경, 🔴 {red_count}건 제외", file=sys.stderr)
        expired_titles, new_added, updated_titles, crawled = [], [], [], []

    else:
        kept_items, expired_titles = expire_items(existing_items)
        if expired_titles:
            print(f"[expire] {len(expired_titles)}건 삭제", file=sys.stderr)

        known_sns = {it["pbancSn"] for it in kept_items if it.get("pbancSn")}
        crawled = crawl(known_sns)
        kept_by_sn = {it["pbancSn"]: it for it in kept_items if it.get("pbancSn")}

        red_count = 0
        new_added = []
        updated_titles = []

        for crawled_item in crawled:
            sn = crawled_item["pbancSn"]
            tier, evidence = classify(crawled_item)
            reason = evidence.get("summary_reason", "")

            if tier == "red":
                red_count += 1
                if sn in kept_by_sn:
                    kept_items = [it for it in kept_items if it.get("pbancSn") != sn]
                continue

            if sn in kept_by_sn:
                existing = kept_by_sn[sn]
                existing["last_seen"] = TODAY
                changed = False
                new_deadline = crawled_item.get("deadline", "") or existing.get("deadline", "")
                new_title = crawled_item.get("title", "") or existing.get("title", "")
                new_agency = crawled_item.get("agency", "") or existing.get("agency", "")
                for field, new_val, old_key in [
                    ("tier", tier, "tier"),
                    ("deadline", new_deadline, "deadline"),
                    ("title", new_title, "title"),
                    ("note", reason, "note"),
                    ("agency", new_agency, "agency"),
                ]:
                    if existing.get(old_key) != new_val and new_val:
                        changed = True
                existing.update({
                    "tier": tier, "note": reason,
                    "classify_evidence": evidence,
                    "deadline": new_deadline, "title": new_title,
                })
                if new_agency:
                    existing["agency"] = new_agency
                if crawled_item.get("structured"):
                    existing["structured"] = crawled_item["structured"]
                if changed:
                    existing["last_changed_at"] = TODAY
                    updated_titles.append(existing.get("title", ""))
                    # 티어 변경으로 🟢🟡 진입 시 raw_content 재수집 예약
                    if tier in FETCH_TIERS and not existing.get("raw_content"):
                        existing.pop("raw_fetched_at", None)
            else:
                new_item = {
                    "pbancSn": sn,
                    "title": crawled_item["title"],
                    "agency": crawled_item.get("agency", ""),
                    "deadline": crawled_item.get("deadline", ""),
                    "url": crawled_item.get("url", ""),
                    "tier": tier,
                    "note": reason,
                    "classify_evidence": evidence,
                    "first_seen": TODAY,
                    "last_seen": TODAY,
                    "structured": crawled_item.get("structured", {}),
                }
                kept_items.append(new_item)
                new_added.append(new_item["title"])

        # ── ITP (인천테크노파크 지원사업) 추가 크롤 ──────────────
        try:
            itp_items = crawl_itp(known_sns)
        except Exception as e:
            print(f"[itp] 크롤 실패: {e}", file=sys.stderr)
            itp_items = []
        # kept_by_sn 갱신 (위에서 K-Startup 신규 추가됐으므로)
        kept_by_sn = {it["pbancSn"]: it for it in kept_items if it.get("pbancSn")}
        for itp_item in itp_items:
            sn = itp_item["pbancSn"]  # itp_<seq>
            tier, evidence = classify_itp(itp_item)
            reason = evidence.get("summary_reason", "")
            if sn in kept_by_sn:
                existing = kept_by_sn[sn]
                existing["last_seen"] = TODAY
                new_deadline = itp_item.get("deadline", "") or existing.get("deadline", "")
                changed = (
                    existing.get("tier") != tier
                    or existing.get("deadline") != new_deadline
                    or existing.get("title") != itp_item.get("title", "")
                )
                existing.update({
                    "tier": tier, "note": reason,
                    "classify_evidence": evidence,
                    "deadline": new_deadline,
                    "title": itp_item.get("title", existing.get("title", "")),
                    "agency": itp_item.get("agency", existing.get("agency", "")),
                    "url": itp_item.get("url", existing.get("url", "")),
                    "structured": itp_item.get("structured", existing.get("structured", {})),
                })
                if changed:
                    existing["last_changed_at"] = TODAY
                    updated_titles.append(existing.get("title", ""))
            else:
                new_item = {
                    "pbancSn": sn,
                    "title": itp_item["title"],
                    "agency": itp_item.get("agency", ""),
                    "deadline": itp_item.get("deadline", ""),
                    "url": itp_item.get("url", ""),
                    "tier": tier,
                    "note": reason,
                    "classify_evidence": evidence,
                    "first_seen": itp_item.get("first_seen", TODAY),
                    "last_seen": TODAY,
                    "structured": itp_item.get("structured", {}),
                }
                kept_items.append(new_item)
                new_added.append(new_item["title"])
        print(f"[itp] {len(itp_items)}건 처리 완료", file=sys.stderr)

        # ── 외부 소스 (BIZINFO + KOCCA) 추가 크롤 (2026-05-12 신규) ──
        ext_items = crawl_external_sources(known_sns)
        # dedup 키: id(=pbancSn) 기준 — bizinfo_PBLN_..., kocca_intcNo
        # 기존 풀의 source=bizinfo 항목들은 'id' 필드를 dedup 키로 가짐
        kept_by_id = {}
        for it in kept_items:
            for k in (it.get("pbancSn"), it.get("id")):
                if k and k != "None":
                    kept_by_id[k] = it
        for ext in ext_items:
            ext_id = ext["id"]
            if ext_id in kept_by_id:
                existing = kept_by_id[ext_id]
                existing["last_seen"] = TODAY
                # source/source_label 보강 (기존이 없으면)
                existing.setdefault("source", ext["source"])
                existing.setdefault("source_label", ext["source_label"])
                existing.setdefault("id", ext_id)
                # 마감/제목/agency/url 갱신 (새 값 있으면)
                if ext.get("deadline"):
                    existing["deadline"] = ext["deadline"]
                if ext.get("title"):
                    existing["title"] = ext["title"]
                if ext.get("agency"):
                    existing["agency"] = ext["agency"]
                if ext.get("url"):
                    existing["url"] = ext["url"]
                # tier/note 재분류 결과 반영 (티어 떨어지는 것도 OK)
                prev_tier = existing.get("tier")
                existing["tier"] = ext["tier"]
                existing["note"] = ext["note"]
                existing["classify_evidence"] = ext["classify_evidence"]
                if ext.get("structured"):
                    existing["structured"] = ext["structured"]
                if prev_tier != ext["tier"]:
                    existing["last_changed_at"] = TODAY
                    updated_titles.append(existing.get("title", ""))
            else:
                kept_items.append(ext)
                new_added.append(ext["title"])
        print(f"[external] {len(ext_items)}건 처리 완료", file=sys.stderr)

    tier_order = {"green": 0, "yellow": 1, "orange": 2}
    kept_items.sort(key=lambda x: (
        tier_order.get(x.get("tier", "orange"), 9),
        x.get("deadline") or "9999-99-99",
    ))

    # 🟢🟡 원문 fetch
    enrich_raw_content(kept_items)

    # history
    history = prune_history(pool.get("history", []), now_kst)
    history.append({
        "date": TODAY,
        "at_kst": now_kst.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "new": len(new_added),
        "updated": len(updated_titles),
        "expired": len(expired_titles),
        "total": len(kept_items),
        "red_excluded": red_count,
    })
    seen = set()
    deduped = [h for h in reversed(history) if h["date"] not in seen and not seen.add(h["date"])]
    pool["history"] = list(reversed(deduped))

    pool["items"] = kept_items
    pool["red_count_today"] = red_count
    pool["_meta"] = {
        "expired": expired_titles,
        "new_added": new_added,
        "updated_today": updated_titles,
        "stats": {
            "green": sum(1 for i in kept_items if i.get("tier") == "green"),
            "yellow": sum(1 for i in kept_items if i.get("tier") == "yellow"),
            "orange": sum(1 for i in kept_items if i.get("tier") == "orange"),
            "red_excluded": red_count,
            "expired_removed": len(expired_titles),
            "total_pool": len(kept_items),
            "rss_total": len(crawled) if not args.skip_crawl else 0,
            "raw_fetched": sum(1 for i in kept_items if i.get("raw_content")),
        },
    }
    save_pool(pool, now_kst)

    stats = pool["_meta"]["stats"]
    print(f"\n{'='*50}", file=sys.stderr)
    print(
        f"[결과] nidview {stats['rss_total']} → "
        f"🟢{stats['green']} 🟡{stats['yellow']} 🟠{stats['orange']} 🔴{stats['red_excluded']} | "
        f"신규 {len(new_added)} · 수정 {len(updated_titles)} · 만료 {stats['expired_removed']} · "
        f"풀 {stats['total_pool']} · 원문 {stats['raw_fetched']}건",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
