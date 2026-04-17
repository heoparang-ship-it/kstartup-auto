#!/usr/bin/env python3
"""
K-Startup 공고 자동 업데이트 오케스트레이터 v3
RSS 크롤 → 규칙 분류 → 만료 삭제 → upsert → Haiku deep_summary 생성 → 저장

v3 추가사항:
- updated_at_kst (ISO 시:분까지)
- history[] 최근 30일 갱신 이력
- deep_summary{} — 신규 공고만 Anthropic Haiku로 5개 섹션 요약 생성 (캐싱)

Usage: python update.py
"""
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from crawl import crawl
from classify import classify, TODAY

KST = timezone(timedelta(hours=9))
POOL_FILE = "recommendations.json"
STALE_DAYS = 14
HISTORY_MAX_DAYS = 30

# ── Haiku deep_summary 설정 ──
HAIKU_MODEL = "claude-haiku-4-5-20251001"
HAIKU_MAX_NEW_PER_RUN = 10   # 1회 실행 당 최대 호출 건수 (비용 상한)
HAIKU_TIMEOUT_S = 60

DEEP_SUMMARY_SYSTEM = """당신은 sinhon.life (B2C 신혼부부 라이프스타일 플랫폼) 허파랑 대표의 정부지원사업 컨설턴트입니다.

사업 컨텍스트:
- 도메인: sinhon.life
- 카테고리: B2C 신혼부부 라이프스타일 플랫폼 (결혼준비·허니문·혼수·신혼살림)
- 기술: Next.js + Claude API(AI 비서), PWA
- BM: 무료 + CPC 광고 + 제휴 수수료
- 소재지: 인천 (허파랑 대표, XCom 법인)
- 이중 트랙: 트랙 A 초기창업(허파랑, 법인 3년 이내) / 트랙 B 예비창업(배우자, 사업자 전)

공고를 분석해 다음 JSON 스키마에 정확히 맞춰 응답하세요. 다른 텍스트 없이 순수 JSON만 출력하세요:

{
  "fit": "왜 sinhon.life와 맞는지 구체적으로 2-3문장. 공고의 특징 + 신혼생활의 어떤 포인트와 연결되는지 명시",
  "strategy": ["지원 포지셔닝 액션 1 (구체적)", "액션 2", "액션 3"],
  "checkpoints": ["지원 전 확인 필수사항 1 (자격·서류·지역 등)", "확인사항 2", "확인사항 3"],
  "difficulty": "low|medium|high",
  "next_action": "오늘~이번주 안에 해야 할 가장 첫 실행 액션 1개 (구체적, 15자 이내)"
}"""


def load_pool() -> dict:
    try:
        with open(POOL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("schema_version") not in (2, 3):
            raise ValueError("schema mismatch")
        # v2 → v3 마이그레이션
        data["schema_version"] = 3
        data.setdefault("history", [])
        return data
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {
            "schema_version": 3,
            "last_updated": TODAY,
            "updated_at_kst": "",
            "history": [],
            "items": [],
            "red_count_today": 0,
        }


def save_pool(pool: dict, now_kst: datetime):
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


# ── Haiku deep_summary 생성 ───────────────────────────────────
def _parse_json_response(text: str):
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except Exception:
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            data = json.loads(text[start:end])
        except Exception:
            return None
    required = {"fit", "strategy", "checkpoints", "difficulty", "next_action"}
    if not required.issubset(data.keys()):
        return None
    if not isinstance(data.get("strategy"), list) or not isinstance(data.get("checkpoints"), list):
        return None
    if data.get("difficulty") not in ("low", "medium", "high"):
        data["difficulty"] = "medium"
    return data


def generate_deep_summary(client, item: dict):
    user_msg = (
        f"공고:\n"
        f"- 제목: {item.get('title', '')}\n"
        f"- 주관기관: {item.get('agency', '') or '(미상)'}\n"
        f"- 마감일: {item.get('deadline', '') or '(미확인)'}\n"
        f"- 티어: {item.get('tier', '')}\n"
        f"- 매칭 이유: {item.get('note', '')}\n\n"
        f"JSON만 응답하세요."
    )
    try:
        resp = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=600,
            system=DEEP_SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            timeout=HAIKU_TIMEOUT_S,
        )
        text = resp.content[0].text if resp.content else ""
        parsed = _parse_json_response(text)
        if parsed is None:
            print(f"[haiku] 파싱 실패: {item.get('pbancSn')} — {text[:80]}", file=sys.stderr)
            return None
        return parsed
    except Exception as e:
        print(f"[haiku] 호출 실패 ({item.get('pbancSn')}): {e}", file=sys.stderr)
        return None


def enrich_deep_summaries(items: list):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("[haiku] ANTHROPIC_API_KEY 없음 — deep_summary 생성 스킵", file=sys.stderr)
        return (0, 0)

    missing = [it for it in items if not it.get("deep_summary")]
    if not missing:
        print("[haiku] 모든 항목에 deep_summary 존재 — 스킵", file=sys.stderr)
        return (0, 0)

    tier_order = {"green": 0, "orange": 1, "yellow": 2}
    missing.sort(key=lambda x: tier_order.get(x.get("tier", "yellow"), 9))
    to_process = missing[:HAIKU_MAX_NEW_PER_RUN]

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
    except ImportError:
        print("[haiku] anthropic 패키지 없음 — deep_summary 생성 스킵", file=sys.stderr)
        return (0, 0)

    print(f"[haiku] deep_summary 생성 대상 {len(to_process)}건 (전체 누락 {len(missing)}건)", file=sys.stderr)

    succ = 0
    for item in to_process:
        ds = generate_deep_summary(client, item)
        if ds:
            item["deep_summary"] = ds
            succ += 1
            print(f"[haiku] OK {item.get('pbancSn')}: {item.get('title', '')[:30]}...", file=sys.stderr)
        time.sleep(0.2)

    return (succ, len(to_process))


# ── 메인 ──────────────────────────────────────────────────────
def main():
    now_kst = datetime.now(KST)

    pool = load_pool()
    existing_items = pool.get("items", [])
    print(f"[load] 기존 풀: {len(existing_items)}건", file=sys.stderr)

    kept_items, expired_titles = expire_items(existing_items)
    if expired_titles:
        print(f"[expire] {len(expired_titles)}건 삭제", file=sys.stderr)

    known_sns = {it["pbancSn"] for it in kept_items if it.get("pbancSn")}
    crawled = crawl(known_sns)

    kept_by_sn = {it["pbancSn"]: it for it in kept_items if it.get("pbancSn")}

    red_count = 0
    new_added = []

    for crawled_item in crawled:
        sn = crawled_item["pbancSn"]
        tier, reason = classify(crawled_item)

        if tier == "red":
            red_count += 1
            if sn in kept_by_sn:
                kept_items = [it for it in kept_items if it.get("pbancSn") != sn]
            continue

        if sn in kept_by_sn:
            existing = kept_by_sn[sn]
            existing["last_seen"] = TODAY
            existing["tier"] = tier
            if crawled_item.get("agency") and not existing.get("agency"):
                existing["agency"] = crawled_item["agency"]
        else:
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

    tier_order = {"green": 0, "orange": 1, "yellow": 2}
    kept_items.sort(key=lambda x: (
        tier_order.get(x.get("tier", "yellow"), 9),
        x.get("deadline") or "9999-99-99",
    ))

    # deep_summary 생성 (캐시 있으면 재사용)
    ds_succ, ds_attempt = enrich_deep_summaries(kept_items)

    # history 기록
    history = prune_history(pool.get("history", []), now_kst)
    history.append({
        "date": TODAY,
        "at_kst": now_kst.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "new": len(new_added),
        "expired": len(expired_titles),
        "total": len(kept_items),
        "red_excluded": red_count,
        "deep_summary_generated": ds_succ,
    })
    # 같은 날짜 중복 제거 (최신만 유지)
    seen = set()
    deduped = []
    for h in reversed(history):
        if h["date"] in seen:
            continue
        seen.add(h["date"])
        deduped.append(h)
    pool["history"] = list(reversed(deduped))

    pool["items"] = kept_items
    pool["red_count_today"] = red_count
    pool["_meta"] = {
        "expired": expired_titles,
        "new_added": new_added,
        "deep_summary": {"generated": ds_succ, "attempted": ds_attempt},
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
    save_pool(pool, now_kst)

    stats = pool["_meta"]["stats"]
    print(f"\n{'='*50}", file=sys.stderr)
    print(f"[결과] RSS {stats['rss_total']} → 🟢{stats['green']} 🟡{stats['yellow']} 🟠{stats['orange']} 🔴{stats['red_excluded']} | "
          f"신규 {len(new_added)} · 만료 {stats['expired_removed']} · 풀 {stats['total_pool']} · "
          f"Haiku {ds_succ}/{ds_attempt}건", file=sys.stderr)


if __name__ == "__main__":
    main()
