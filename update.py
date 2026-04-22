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
    """🟢🟡 신규 항목(raw_content 없음)에 한해 원문 fetch 후 저장."""
    targets = [
        it for it in items
        if it.get("tier") in FETCH_TIERS and not it.get("raw_content")
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
