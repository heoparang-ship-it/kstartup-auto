#!/usr/bin/env python3
"""
K-Startup 공고 자동 업데이트 오케스트레이터
RSS 크롤 → 규칙 분류 → 만료 삭제 → upsert → 저장

Usage: python update.py
"""
import json
import sys
from datetime import datetime, timezone, timedelta

from crawl import crawl
from classify import classify, TODAY

KST = timezone(timedelta(hours=9))
POOL_FILE = "recommendations.json"
STALE_DAYS = 14  # last_seen이 이보다 오래되면 삭제


def load_pool() -> dict:
    """기존 풀을 로드한다."""
    try:
        with open(POOL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("schema_version") != 2:
            raise ValueError("schema mismatch")
        return data
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {
            "schema_version": 2,
            "last_updated": TODAY,
            "items": [],
            "red_count_today": 0,
        }


def save_pool(pool: dict):
    """풀을 저장한다."""
    pool["last_updated"] = TODAY
    with open(POOL_FILE, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)
    print(f"[save] {POOL_FILE} 저장 완료 ({len(pool['items'])}건)", file=sys.stderr)


def expire_items(items: list[dict]) -> tuple[list[dict], list[str]]:
    """만료/stale 항목을 삭제한다. (kept, expired_titles) 반환."""
    stale_cutoff = (datetime.now(KST) - timedelta(days=STALE_DAYS)).strftime("%Y-%m-%d")
    kept = []
    expired_titles = []

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


def main():
    # 1. 기존 풀 로드
    pool = load_pool()
    existing_items = pool.get("items", [])
    existing_by_sn = {it["pbancSn"]: it for it in existing_items if it.get("pbancSn")}
    print(f"[load] 기존 풀: {len(existing_items)}건", file=sys.stderr)

    # 2. 만료 삭제
    kept_items, expired_titles = expire_items(existing_items)
    if expired_titles:
        print(f"[expire] {len(expired_titles)}건 삭제: {expired_titles[:5]}", file=sys.stderr)

    # 3. RSS 크롤
    known_sns = {it["pbancSn"] for it in kept_items if it.get("pbancSn")}
    crawled = crawl(known_sns)

    # 4. RSS에 있는 SN 집합 (= 현재 모집중)
    rss_sns = {it["pbancSn"] for it in crawled}

    # 5. 기존 풀 중 RSS에 없는 항목 — 모집 종료 가능성
    #    last_seen 업데이트 안 함 → stale 로직으로 자연 삭제
    kept_by_sn = {it["pbancSn"]: it for it in kept_items if it.get("pbancSn")}

    # 6. 분류 + upsert
    red_count = 0
    new_added = []

    for crawled_item in crawled:
        sn = crawled_item["pbancSn"]
        tier, reason = classify(crawled_item)

        if tier == "red":
            red_count += 1
            # 기존 풀에 있었으메 제거
            if sn in kept_by_sn:
                kept_items = [it for it in kept_items if it.get("pbancSn") != sn]
            continue

        if sn in kept_by_sn:
            # 기존 항목 업데이트
            existing = kept_by_sn[sn]
            existing["last_seen"] = TODAY
            existing["tier"] = tier
            # agency가 비어있었는데 새로 알게 되면 보강
            if crawled_item.get("agency") and not existing.get("agency"):
                existing["agency"] = crawled_item["agency"]
        else:
            # 신규 항목 추가
            new_item = {
                "pbancSn": sn,
                "title": crawled_item["title"],
                "agency": crawled_item.get("agency", ""),
                "deadline": crawled_item.get("deadline", ""),
                "url": crawled_item.get("url", ""),
                "tier": tier,
                "note": reason,
                "first_seen": TODAY,
                "last_seen": TODAY,
            }
            kept_items.append(new_item)
            new_added.append(new_item["title"])

    # 7. 정렬: green → orange → yellow, 그 안에서 마감일 순
    tier_order = {"green": 0, "orange": 1, "yellow": 2}
    kept_items.sort(key=lambda x: (
        tier_order.get(x.get("tier", "yellow"), 9),
        x.get("deadline") or "9999-99-99",
    ))

    # 8. 저장
    pool["items"] = kept_items
    pool["red_count_today"] = red_count
    pool["_meta"] = {
        "expired": expired_titles,
        "new_added": new_added,
        "stats": {
            "green": sum(1 for i in kept_items if i.get("tier") == "green"),
            "yellow": sum(1 for i in kept_items if i.get("tier") == "yellow"),
            "orange": sum(1 for i in kept_items if i.get("tier") == "orange"),
            "red_excluded": red_count,
            "expired_removed": len(expired_titles),
            "total_pool": len(kept_items),
            "rss_total": len(crawled),
        },
    }
    save_pool(pool)

    # 9. 리포트
    stats = pool["_meta"]["stats"]
    print(f"\n{'='*50}", file=sys.stderr)
    print(f"[결과] RSS {stats['rss_total']}건 → "
          f"🟢{stats['green']} 🟡{stats['yellow']} 🟠{stats['orange']} "
          f"🔴{stats['red_excluded']}제외 | "
          f"신규 {len(new_added)}건, 만료삭제 {stats['expired_removed']}건, "
          f"풀 {stats['total_pool']}건", file=sys.stderr)
    if new_added:
        print(f"[신규] {new_added[:10]}", file=sys.stderr)


if __name__ == "__main__":
    main()
