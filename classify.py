#!/usr/bin/env python3
"""
K-Startup 공고 자동 분류기 v6 — 구조화 필드 우선
────────────────────────────────────────────────
v5 대비 개선:
1. profile.md 규칙은 유지 (🔴/🟢/🟡/🟠 tier, default=RED)
2. 1차 필터: structured.{region,biz_enyy,biz_class,recruiting,exclude_target}
   → nidview API가 제공하는 공식 필드로 판정 (문자열 매칭보다 정확)
3. 2차 필터: title + agency + content 문자열 매칭 (v5 로직 보강)
4. 제외대상(aply_excl_trgt_ctnt) 필드 반영 — 명시적 배제 공고 즉시 RED

입력: crawl_v6.py 출력(JSON 배열, structured 필드 포함)
출력: recommendations.json 호환 포맷 (v5와 동일 스키마)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y-%m-%d")

# ══════════════════════════════════════════════════════════════
# 구조화 필드 필터 세트 (nidview API 값 기반)
# ══════════════════════════════════════════════════════════════

# structured.region 값 중 🟢 수용 (전국 또는 인천)
GREEN_REGIONS = {"전국", "인천"}

# structured.region 값 중 🔴 즉시 제외 (단독 지방 지역)
RED_REGIONS_EXCLUSIVE = {
    "부산", "대구", "대전", "광주", "울산", "세종",
    "강원", "충북", "충남", "전북", "전남",
    "경북", "경남", "제주",
    # 경기·서울 단독은 구조화 필드 판정에서 RED (복합 키워드는 아래 check)
}

# structured.biz_class 값 중 🔴 (단순 행사/컨설팅 — 실익 낮음)
# 주의: "행사ㆍ네트워크" 는 가끔 유용할 수 있어 RED 아님 → YELLOW
RED_BIZ_CLASS = {
    # 의도적으로 비워둠. 대신 긍정적 분류에서만 YELLOW/GREEN으로 승격
}

GREEN_BIZ_CLASS = {"사업화", "정책자금", "융자ㆍ보증"}
YELLOW_BIZ_CLASS = {"멘토링ㆍ컨설팅ㆍ교육", "시설ㆍ공간ㆍ보육", "창업교육",
                    "기술개발(R&D)", "기술개발(R&amp;D)", "인력",
                    "판로ㆍ해외진출", "글로벌"}

# structured.biz_enyy: "예비창업자/1년미만/…10년미만" 콤마 구분
# 허파랑(2026-04 기준, 1년 미만 창업자) 적용 가능한 값
ACCEPTABLE_BIZ_ENYY = {
    "예비창업자", "1년미만", "2년미만", "3년미만",
    "5년미만", "7년미만", "10년미만",
}

# ══════════════════════════════════════════════════════════════
# 문자열 매칭 키워드 (v5 로직 유지 + 보강)
# ══════════════════════════════════════════════════════════════

RED_INDUSTRY = [
    "반도체", "팹리스", "바이오", "농업", "에너지", "방산", "로봇", "항공우주",
    "관광", "게임", "가구", "세라믹", "해운물류", "패션", "의료기기", "의료",
    "제조", "식품", "농식품", "수산", "축산", "원자력", "조선", "섬유",
    "화학", "철강", "자동차부품", "전통문화", "전통시장", "전통주",
    "한복", "뷰티", "화장품", "제약", "신약", "의약품",
    "건설", "건축", "부동산", "물류", "유통", "프랜차이즈",
    "농생명", "스마트팜", "스마트공장", "그린", "탄소중립", "ESG",
    "웰니스", "헬스케어", "메디컬", "디바이스",
    "모빌리티", "자율주행", "드론", "UAM", "우주", "위성",
    "메타버스", "블록체인", "NFT", "Web3", "핀테크",
    "스포츠산업", "스포츠", "e스포츠",
]

RED_QUALIFICATION = [
    "OASIS", "이민자", "외국인", "여성전용", "여성창업", "여성기업",
    "제대군인", "자립청년", "소상공인전용",
    "귀농", "귀촌", "다문화", "장애인", "북한이탈주민", "탈북",
    "시니어", "중장년", "4050", "경력보유여성",
    "고졸", "특성화고", "마이스터고",
    "농업인", "어업인", "임업인",
    "사회적기업가", "협동조합", "마을기업", "자활기업",
]

RED_STAGE = [
    "후속지원", "Series A", "Series B", "Series C", "IPO",
    "수출실적", "업력 3년 초과", "업력 5년 초과", "업력 7년 초과",
    "재도전", "재창업", "도약패키지", "성장도약",
    "스케일업", "scale-up", "Scale-Up",
]

RED_NATURE = [
    "수행기관", "수행사", "운영기관 모집", "위탁운영",
    "B2G", "공공시장 진출", "공공조달", "조달시장",
    "주관기관 모집", "주관기관모집",
    "멘토 모집", "멘토단 모집", "멘토링 멘토",
    "심사위원 모집", "심사역 모집", "평가위원 모집",
    "비상근 감사", "비상근감사",
    "운영 인력", "운영인력 모집",
    "코디네이터 모집", "매니저 모집",
    "입찰", "용역", "제안요청",
    "투자조합 결성", "출자기관",
    "우수기업 인증", "인증심사", "적합성 인증",
    "특허출원", "특허등록",
]

SEOUL_25_GU = [
    "강남구", "서초구", "관악구", "은평구", "노원구", "동작구",
    "성북구", "성동구", "마포구", "용산구", "종로구",
    "동대문구", "광진구", "서대문구", "양천구", "영등포구",
    "구로구", "금천구", "도봉구", "강북구", "중랑구",
    "강서구", "강동구", "송파구",
]

RED_SEOUL_FACILITY = [
    "서울창업허브", "서울 입주", "성수 입주", "마포 입주", "강남 입주",
    "서울 소재", "서초 소재", "성수동", "역삼동", "선릉",
    "판교", "성남", "파주",
    "서울숲", "합정", "홍대입구", "신촌",
    "서울 캠퍼스", "서울캠퍼스",
]

SEOUL_UNIVERSITY = [
    "서울대", "연세대", "고려대", "성균관대", "한양대학교 서울",
    "이화여대", "중앙대", "경희대학교 서울", "한국외대", "건국대",
    "동국대", "홍익대학교 서울", "숭실대", "세종대", "국민대",
    "숙명여대", "상명대", "서울시립대", "서울과기대", "서경대",
    "삼육대", "한성대", "광운대", "명지대", "덕성여대",
    "서울여대", "성공회대", "총신대", "서강대", "가톨릭대",
]

# ══════════════════════════════════════════════════════════════
# 긍정 키워드
# ══════════════════════════════════════════════════════════════

GREEN_KEYWORDS = [
    "예비창업패키지", "초기창업패키지", "예비창업", "초기창업",
    "모두의 창업", "모두의창업", "유니콘 브릿지", "유니콘브릿지",
    "K-Startup 챌린지",
]

GREEN_INCHEON = [
    "인천창조경제혁신센터", "인천테크노파크", "인천스타트업파크",
    "남동구", "인천 청년", "인천창업",
    "인천글로벌스케일업", "ICCE", "인천TP",
    "연수구 창업", "미추홀", "인천경제자유구역",
]

YELLOW_KEYWORDS = [
    "액셀러레이팅", "액셀러레이터", "청년창업", "IP디딤돌", "IP 디딤돌",
    "콘텐츠", "IT", "디지털", "플랫폼", "SaaS", "B2C",
    "해커톤", "데모데이", "피칭", "IR",
    "TIPS", "Pre-TIPS", "프리팁스",
    "창업성공패키지", "창업도전",
    "기술창업", "혁신창업",
    "크리에이터", "1인미디어", "미디어",
    "마케팅바우처", "마케팅 바우처",
    "임팩트", "소셜벤처", "소셜 벤처",
]

ORANGE_KEYWORDS = [
    "AX", "LLM", "AI대전환", "AI 대전환", "AI바우처", "AI 바우처",
    "AI 실증", "인공지능", "클라우드", "데이터",
    "AI이노베이션", "AI 이노베이션",
    "AI 스타트업", "AI스타트업",
    "딥테크", "deep tech", "DeepTech",
    "생성형 AI", "생성형AI", "GenAI",
]


# ══════════════════════════════════════════════════════════════
# 분류 로직
# ══════════════════════════════════════════════════════════════

def check_structured_red(s: dict) -> str | None:
    """구조화 필드만으로 판정 가능한 🔴 사유 반환. 없으면 None."""
    # 모집 종료
    if s.get("recruiting") is False:
        return "모집 종료 (recruiting=N)"
    # 마감일 경과
    end = s.get("end_date") or ""
    if end and end < TODAY:
        return f"마감일 경과 ({end})"
    # 지역 단독
    region = (s.get("region") or "").strip()
    if region in RED_REGIONS_EXCLUSIVE:
        return f"지역 한정 ({region})"
    # 업력 허용 없음: biz_enyy 가 비어있지 않고, 허용 집합과 교집합이 없으면 RED
    enyy = (s.get("biz_enyy") or "").strip()
    if enyy:
        parts = {p.strip() for p in enyy.split(",") if p.strip()}
        if parts and not (parts & ACCEPTABLE_BIZ_ENYY):
            return f"업력 불일치 (biz_enyy={enyy})"
    # 제외대상 명시 — 간단 키워드 매칭
    excl = (s.get("exclude_target") or "").strip()
    if excl:
        for kw in ("대기업", "중견기업", "공공기관 재직자", "휴·폐업"):
            if kw in excl:
                return f"제외대상 명시 ({kw})"
    return None


def check_structured_green(s: dict) -> str | None:
    """구조화 필드가 강하게 🟢를 시사하면 사유 반환. 아니면 None."""
    region = (s.get("region") or "").strip()
    biz_class = (s.get("biz_class") or "").strip()
    if region in GREEN_REGIONS and biz_class in GREEN_BIZ_CLASS:
        return f"우선 매칭 ({region}/{biz_class})"
    return None


def check_keyword_red(combined: str) -> str | None:
    for kw in RED_INDUSTRY:
        if kw in combined:
            return f"업종 한정 ({kw})"
    for kw in RED_QUALIFICATION:
        if kw in combined:
            return f"자격 한정 ({kw})"
    for kw in RED_STAGE:
        if kw in combined:
            return f"단계 불일치 ({kw})"
    for kw in RED_NATURE:
        if kw in combined:
            return f"성격 불일치 ({kw})"
    return None


def check_region_keyword_red(combined: str, struct_region: str) -> str | None:
    """문자열에서 서울/경기 단독 판정.
    ⚠️ 서울 시설/구/대학은 structured.region 값과 무관하게 항상 체크
       (예: 'structured.region=전국'이어도 title에 '서울창업허브 성수'가 있으면 RED)
    """
    # 서울 시설/구/대학 — region과 무관하게 항상 검사
    for kw in RED_SEOUL_FACILITY:
        if kw in combined:
            return f"서울 시설/지자체 ({kw})"
    for gu in SEOUL_25_GU:
        if gu in combined:
            return f"서울 구 단독 ({gu})"
    for uni in SEOUL_UNIVERSITY:
        if uni in combined:
            return f"서울 대학 ({uni})"

    # 이하 '서울/경기 단독' 판정은 structured.region이 '전국'/'인천'이 아닐 때만
    if struct_region in GREEN_REGIONS:
        return None

    if "서울" in combined:
        for safe in ("오픈이노베이션", "온라인", "비대면", "화상", "전국"):
            if safe in combined:
                return None
        return "서울 단독 (인천 미포함)"
    if "경기" in combined and "인천" not in combined:
        return "경기 단독 (인천 미포함)"
    return None


def classify(item: dict) -> tuple[str, str]:
    """
    공고 1건을 분류. Returns (tier, reason).
    우선순위: 구조화 RED → 키워드 RED → 구조화 GREEN → 키워드 GREEN → YELLOW → ORANGE → RED(default)
    """
    title = item.get("title", "")
    agency = item.get("agency", "")
    s = item.get("structured", {}) or {}
    content = (s.get("content") or "")
    # 문자열 검사는 title+agency+apply_target_desc 중심 (content는 너무 많은 false positive)
    combined = f"{title} {agency} {s.get('apply_target_desc','')}"

    # 1) 구조화 필드 RED
    r = check_structured_red(s)
    if r:
        return "red", r

    # 2) 키워드 RED (업종/자격/단계/성격)
    r = check_keyword_red(combined)
    if r:
        return "red", r

    # 3) 지역 RED (구조화 region이 전국/인천 아닌 상태에서 서울/경기 단독 검출)
    r = check_region_keyword_red(combined, (s.get("region") or "").strip())
    if r:
        return "red", r

    # 4) 구조화 GREEN
    g = check_structured_green(s)
    if g:
        return "green", g

    # 5) 키워드 GREEN
    for kw in GREEN_KEYWORDS:
        if kw in combined:
            return "green", f"핵심 매칭 ({kw})"
    for kw in GREEN_INCHEON:
        if kw in combined:
            return "green", f"인천 매칭 ({kw})"

    # 6) 구조화 YELLOW (지역 OK + 사업 분류가 YELLOW 세트)
    region = (s.get("region") or "").strip()
    biz_class = (s.get("biz_class") or "").strip()
    if region in GREEN_REGIONS and biz_class in YELLOW_BIZ_CLASS:
        return "yellow", f"검토 매칭 ({region}/{biz_class})"

    # 7) 키워드 YELLOW
    for kw in YELLOW_KEYWORDS:
        if kw in combined:
            return "yellow", f"검토 매칭 ({kw})"

    # 8) 키워드 ORANGE (AI)
    for kw in ORANGE_KEYWORDS:
        if kw in combined:
            return "orange", f"AI 포지셔닝 ({kw})"

    # 9) Default = RED
    return "red", "기본 제외 (긍정 매칭 없음)"


# ══════════════════════════════════════════════════════════════
# 풀 머지 / 입출력
# ══════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("Usage: python classify_v6.py <crawl_results.json> [existing_pool.json] > recommendations.json",
              file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        crawled = json.load(f)

    existing_pool = {
        "schema_version": 2, "last_updated": "",
        "items": [], "red_count_today": 0, "reds_today": []
    }
    if len(sys.argv) >= 3:
        try:
            with open(sys.argv[2], "r", encoding="utf-8") as f:
                existing_pool = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    existing_by_sn = {}
    for it in existing_pool.get("items", []):
        sn = it.get("pbancSn", "")
        if sn:
            existing_by_sn[sn] = it

    # 만료 삭제
    expired_titles = []
    stale_cutoff = (datetime.now(KST) - timedelta(days=14)).strftime("%Y-%m-%d")
    kept_items = []
    for it in existing_pool.get("items", []):
        dl = it.get("deadline", "")
        ls = it.get("last_seen", "")
        if dl and dl < TODAY:
            expired_titles.append(it.get("title", ""))
        elif ls and ls < stale_cutoff:
            expired_titles.append(it.get("title", "") + " (stale)")
        else:
            kept_items.append(it)

    all_candidates = crawled if isinstance(crawled, list) else crawled.get("items", [])

    # 재분류
    for it in kept_items:
        tier, reason = classify(it)
        it["_tier"] = tier
        it["_reason"] = reason

    new_items = []
    for it in all_candidates:
        sn = it.get("pbancSn", "")
        tier, reason = classify(it)
        if sn in existing_by_sn:
            existing_by_sn[sn]["last_seen"] = TODAY
            existing_by_sn[sn]["_tier"] = tier
            existing_by_sn[sn]["_reason"] = reason
            if it.get("deadline"):
                existing_by_sn[sn]["deadline"] = it["deadline"]
            # structured 필드 덮어쓰기 (최신 정보)
            if it.get("structured"):
                existing_by_sn[sn]["structured"] = it["structured"]
        else:
            it["first_seen"] = TODAY
            it["last_seen"] = TODAY
            it["_tier"] = tier
            it["_reason"] = reason
            new_items.append(it)

    final_items = []
    red_count = 0
    reds_list = []
    new_added = []

    for it in kept_items + new_items:
        tier = it.pop("_tier", "red")
        reason = it.pop("_reason", "")
        if tier == "red":
            red_count += 1
            reds_list.append({
                "pbancSn": it.get("pbancSn", ""),
                "title": it.get("title", ""),
                "agency": it.get("agency", ""),
                "reason": reason,
            })
        else:
            it["tier"] = tier
            if not it.get("note"):
                it["note"] = reason
            final_items.append(it)
            if it.get("first_seen") == TODAY:
                new_added.append(it.get("title", ""))

    # 티어 우선도 + 마감일순 정렬
    tier_order = {"green": 0, "yellow": 1, "orange": 2}
    final_items.sort(key=lambda x: (
        tier_order.get(x.get("tier"), 9),
        x.get("deadline") or "9999-99-99",
    ))

    result = {
        "schema_version": 3,
        "last_updated": TODAY,
        "red_count_today": red_count,
        "reds_today": reds_list[:100],
        "items": final_items,
        "_meta": {
            "version": "v6",
            "source": "nidview JSON (kisedKstartupService/announcementInformation)",
            "expired_titles": expired_titles,
            "new_added_titles": new_added,
            "needs_review_count": 0,
            "stats": {
                "green": sum(1 for i in final_items if i.get("tier") == "green"),
                "yellow": sum(1 for i in final_items if i.get("tier") == "yellow"),
                "orange": sum(1 for i in final_items if i.get("tier") == "orange"),
                "needs_review": 0,
                "red_excluded": red_count,
                "expired_removed": len(expired_titles),
                "total_pool": len(final_items),
            },
        },
    }

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
