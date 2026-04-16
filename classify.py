#!/usr/bin/env python3
"""
K-Startup 공고 자동 분류기 (profile.md 규칙 기반)
- profile.md의 🔴/🟢/🟡/🟠 규칙을 Python으로 변환
- LLM 토큰 소모 없이 169건+ 공고를 즉시 분류
- 경계 케이스만 "needs_review" 플래그로 LLM에 위임
"""
import json
import re
import sys
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y-%m-%d")

# ── 🔴 즉시 제외 키워드 ──────────────────────────────────────
RED_INDUSTRY = [
    "반도체", "팹리스", "바이오", "농업", "에너지", "방산", "로봇", "항공우주",
    "관광", "게임", "가구", "세라믹", "해운물류", "패션", "의료기기", "의료",
    "제조", "식품", "농식품", "수산", "축산", "원자력", "조선", "섬유",
    "화학", "철강", "자동차부품", "전통문화"
]
RED_QUALIFICATION = [
    "OASIS", "이민자", "외국인", "여성전용", "여성창업", "제대군인", "자립청년",
    "소상공인", "소상공인전용", "귀농", "귀촌", "다문화"
]
RED_STAGE = [
    "후속지원", "Series A", "Series B", "IPO", "수출실적", "업력 3년 초과",
    "업력 5년", "업력 7년", "재도전", "재창업"
]
RED_NATURE = [
    "수행기관", "수행사", "운영기관 모집", "위탁운영", "B2G", "공공시장 진출",
    "공공조달", "조달시장"
]
# 지역: 인천·전국 미포함 단독 지역
RED_REGION_EXCLUSIVE = [
    "부산", "대구", "대전", "광주", "울산", "강원", "충북", "충남", "전북", "전남",
    "경북", "경남", "제주", "세종", "비수도권"
]
# 서울 시설 입주 (본사 이전 요구)
RED_SEOUL_FACILITY = [
    "서울창업허브 입주", "서울 입주", "성수 입주", "마포 입주", "강남 입주",
    "도봉", "구로", "금천", "동대문", "성남", "파주"
]

# ── 🟢 강력 매칭 키워드 ──────────────────────────────────────
GREEN_KEYWORDS = [
    "예비창업패키지", "초기창업패키지", "예비창업", "초기창업",
    "모두의 창업", "모두의창업", "유니콘 브릿지", "유니콘브릿지",
    "사업화", "범용"
]
GREEN_INCHEON = [
    "인천창조경제혁신센터", "인천테크노파크", "인천스타트업파크",
    "남동구", "인천 청년", "인천창업"
]

# ── 🟡 검토 매칭 키워드 ──────────────────────────────────────
YELLOW_KEYWORDS = [
    "액셀러레이팅", "액셀러레이터", "청년창업", "IP디딤돌", "IP 디딤돌",
    "사회적기업", "사회적경제", "콘텐츠", "IT", "디지털",
    "설명회", "교육", "세미나", "네트워킹", "오픈이노베이션",
    "경진대회", "해커톤", "데모데이", "피칭", "IR"
]

# ── 🟠 AI 포지셔닝 키워드 ────────────────────────────────────
ORANGE_KEYWORDS = [
    "AX", "LLM", "AI대전환", "AI 대전환", "AI바우처", "AI 바우처",
    "AI 실증", "인공지능", "클라우드", "데이터"
]

def check_region_red(title: str, agency: str) -> str | None:
    """지역 🔴 판정. 제외 사유 반환, 통과 시 None."""
    combined = title + " " + agency

    # 전국 또는 인천 포함 → 통과
    if "전국" in combined or "인천" in combined or "수도권" in combined:
        return None

    # 서울+경기+인천 통합도 통과
    if "서울" in combined and "경기" in combined and "인천" in combined:
        return None

    # 서울 시설 입주 → 🔴
    for kw in RED_SEOUL_FACILITY:
        if kw in combined:
            return f"서울 시설 입주/지자체 단독 ({kw})"

    # 특정 지역 단독 → 🔴
    for region in RED_REGION_EXCLUSIVE:
        if region in combined:
            # "부산" in title 이지만 "전국" 도 있으면 이미 위에서 통과
            return f"지역 한정 ({region})"

    # 서울 단독 (시설 입주 아닌 경우도 체크)
    if "서울" in combined and "인천" not in combined and "전국" not in combined:
        # 서울 오픈이노베이션 같은 프로그램형은 통과
        if "오픈이노베이션" in combined or "프로그램" in combined or "온라인" in combined:
            return None
        return "서울 단독 (인천 미포함)"

    # 경기 단독
    if "경기" in combined and "인천" not in combined and "전국" not in combined:
        return "경기 단독 (인천 미포함)"

    return None


def classify(item: dict) -> tuple[str, str]:
    """
    공고 1건을 분류. Returns (tier, reason).
    tier: "green" | "yellow" | "orange" | "red" | "needs_review"
    """
    title = item.get("title", "")
    agency = item.get("agency", "")
    combined = title + " " + agency

    # ── 1. 🔴 즉시 제외 ──
    # 업종 한정
    for kw in RED_INDUSTRY:
        if kw in combined:
            return "red", f"업종 한정 ({kw})"

    # 자격 한정
    for kw in RED_QUALIFICATION:
        if kw in combined:
            return "red", f"자격 한정 ({kw})"

    # 단계 불일치
    for kw in RED_STAGE:
        if kw in combined:
            return "red", f"단계 불일치 ({kw})"

    # 성격 불일치
    for kw in RED_NATURE:
        if kw in combined:
            return "red", f"성격 불일치 ({kw})"

    # 지역 🔴
    region_reason = check_region_red(title, agency)
    if region_reason:
        return "red", region_reason

    # ── 2. 만료 체크 ──
    deadline = item.get("deadline", "")
    if deadline and deadline < TODAY:
        return "red", f"마감일 경과 ({deadline})"

    # ── 3. 🟢 강력 매칭 ──
    for kw in GREEN_KEYWORDS:
        if kw in combined:
            return "green", f"핵심 매칭 ({kw})"

    for kw in GREEN_INCHEON:
        if kw in combined:
            return "green", f"인천 지역 매칭 ({kw})"

    # ── 4. 🟡 검토 매칭 ──
    for kw in YELLOW_KEYWORDS:
        if kw in combined:
            return "yellow", f"검토 매칭 ({kw})"

    # ── 5. 🟠 AI 포지셔닝 ──
    for kw in ORANGE_KEYWORDS:
        if kw in combined:
            return "orange", f"AI 포지셔닝 ({kw})"

    # ── 6. 미분류 → LLM 검토 필요 ──
    return "needs_review", "자동 분류 불가 — LLM 검토 필요"


def main():
    """
    stdin 또는 파일에서 크롤 결과 JSON을 읽어 분류 결과를 stdout으로 출력.
    Usage: python classify.py crawl_results.json [existing_pool.json]
    """
    if len(sys.argv) < 2:
        print("Usage: python classify.py <crawl_results.json> [existing_pool.json]", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        crawled = json.load(f)

    # 기존 풀 로드
    existing_pool = {"schema_version": 2, "last_updated": "", "items": [], "red_count_today": 0, "reds_today": []}
    if len(sys.argv) >= 3:
        try:
            with open(sys.argv[2], "r", encoding="utf-8") as f:
                existing_pool = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    # 기존 항목 인덱스 (pbancSn → item)
    existing_by_sn = {}
    for item in existing_pool.get("items", []):
        sn = item.get("pbancSn", "")
        if sn:
            existing_by_sn[sn] = item

    # ── 만료 삭제 ──
    expired_titles = []
    stale_cutoff = (datetime.now(KST) - timedelta(days=14)).strftime("%Y-%m-%d")
    kept_items = []
    for item in existing_pool.get("items", []):
        dl = item.get("deadline", "")
        ls = item.get("last_seen", "")
        if dl and dl < TODAY:
            expired_titles.append(item.get("title", ""))
        elif ls and ls < stale_cutoff:
            expired_titles.append(item.get("title", "") + " (stale)")
        else:
            kept_items.append(item)

    # ── 분류 ──
    greens, yellows, oranges, reds_today, needs_review = [], [], [], [], []

    all_candidates = crawled if isinstance(crawled, list) else crawled.get("items", [])

    # 기존 풀 항목도 재분류
    for item in kept_items:
        tier, reason = classify(item)
        item["_tier"] = tier
        item["_reason"] = reason

    # 신규 크롤 항목 분류
    new_items = []
    for item in all_candidates:
        sn = item.get("pbancSn", "")
        tier, reason = classify(item)

        if sn in existing_by_sn:
            # 기존 항목 업데이트
            existing_by_sn[sn]["last_seen"] = TODAY
            existing_by_sn[sn]["_tier"] = tier
            existing_by_sn[sn]["_reason"] = reason
            if item.get("deadline"):
                existing_by_sn[sn]["deadline"] = item["deadline"]
        else:
            item["first_seen"] = TODAY
            item["last_seen"] = TODAY
            item["_tier"] = tier
            item["_reason"] = reason
            new_items.append(item)

    # 최종 풀 조립
    final_items = []
    red_count = 0
    reds_list = []
    review_list = []
    new_added = []

    for item in kept_items + new_items:
        tier = item.pop("_tier", "red")
        reason = item.pop("_reason", "")

        if tier == "red":
            red_count += 1
            reds_list.append({
                "pbancSn": item.get("pbancSn", ""),
                "title": item.get("title", ""),
                "agency": item.get("agency", ""),
                "reason": reason
            })
        elif tier == "needs_review":
            item["tier"] = "needs_review"
            item["note"] = reason
            review_list.append(item)
        else:
            item["tier"] = tier
            if not item.get("note"):
                item["note"] = reason
            final_items.append(item)
            if item.get("first_seen") == TODAY and item not in kept_items:
                new_added.append(item.get("title", ""))

    # needs_review도 일단 풀에 넣되 플래그 유지 (LLM이 나중에 처리)
    final_items.extend(review_list)

    result = {
        "schema_version": 2,
        "last_updated": TODAY,
        "red_count_today": red_count,
        "reds_today": reds_list,
        "items": final_items,
        "_meta": {
            "expired_titles": expired_titles,
            "new_added_titles": new_added,
            "needs_review_count": len(review_list),
            "stats": {
                "green": sum(1 for i in final_items if i.get("tier") == "green"),
                "yellow": sum(1 for i in final_items if i.get("tier") == "yellow"),
                "orange": sum(1 for i in final_items if i.get("tier") == "orange"),
                "needs_review": len(review_list),
                "red_excluded": red_count,
                "expired_removed": len(expired_titles),
                "total_pool": len(final_items)
            }
        }
    }

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
