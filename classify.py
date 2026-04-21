#!/usr/bin/env python3
"""
K-Startup 공고 자동 분류기 v7 — 구조화 evidence 반환
────────────────────────────────────────────────
v6 대비 개선:
1. 'title 전용 키워드' vs 'all-field 키워드' 분리
   → "예비창업"이 apply_target_desc("예비창업자, 스타트업, 중소기업")에
     걸려 오탐하던 버그 수정 (모든 K-Startup 공고가 이 문구 포함).
2. RED_INDUSTRY 대폭 보강: 3D프린팅·3D프린터·3D모델링·시제품 제작·
   후가공·FAB·금형·메이커·프로토타입 등 제조업 시그널 추가.
3. exclude_target 파싱 보강: '제품·부품의 개발·생산·양산' 같은
   제조업 한정 문구면 risk_flag 추가 (심한 경우 red 승격).
4. classify() 반환 타입 확장: (tier, evidence_dict).
   evidence_dict = {
     summary_reason, category_hints, rule_checks, risk_flags
   }
   update.py는 summary_reason을 그대로 note로 쓰고,
   나머지는 item['evidence']에 직렬화 저장.
5. detect_category_hints(): Haiku 모듈 라우팅용 힌트 태그 산출.

입력: crawl_v6.py 출력(JSON 배열, structured 필드 포함)
출력: recommendations.json 호환 포맷 (v6와 동일 스키마 + evidence)
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

GREEN_REGIONS = {"전국", "인천"}

RED_REGIONS_EXCLUSIVE = {
    "부산", "대구", "대전", "광주", "울산", "세종",
    "강원", "충북", "충남", "전북", "전남",
    "경북", "경남", "제주",
}

RED_BIZ_CLASS: set[str] = set()

GREEN_BIZ_CLASS = {"사업화", "정책자금", "융자ㆍ보증"}
YELLOW_BIZ_CLASS = {"멘토링ㆍ컨설팅ㆍ교육", "시설ㆍ공간ㆍ보육", "창업교육",
                    "기술개발(R&D)", "기술개발(R&amp;D)", "인력",
                    "판로ㆍ해외진출", "글로벌"}

ACCEPTABLE_BIZ_ENYY = {
    "예비창업자", "1년미만", "2년미만", "3년미만",
    "5년미만", "7년미만", "10년미만",
}

# ══════════════════════════════════════════════════════════════
# 문자열 매칭 키워드 (all-fields 대상)
# ══════════════════════════════════════════════════════════════

# 업종 한정(제조·하드웨어·특정 산업) — title/agency/desc 어디 나와도 RED
RED_INDUSTRY = [
    # 하드웨어·제조
    "반도체", "팹리스", "3D프린팅", "3D 프린팅", "3D프린터", "3D 프린터",
    "3D모델링", "3D 모델링", "시제품 제작", "시작품 제작", "시제품제작",
    "시작품제작", "후가공", "금형", "메이커", "프로토타입",
    "FAB", "3D-FAB", "MFG",
    # 바이오·의료
    "바이오", "제약", "신약", "의약품", "의료기기", "의료", "메디컬", "헬스케어",
    "웰니스", "디바이스",
    # 1차산업·식품
    "농업", "농식품", "수산", "축산", "농생명", "스마트팜", "식품",
    # 에너지·중공업
    "에너지", "방산", "로봇", "항공우주", "원자력", "조선", "화학", "철강",
    "자동차부품", "UAM", "우주", "위성",
    # 관광·엔터테인먼트
    "관광", "게임", "e스포츠", "스포츠산업",
    # 공예·전통
    "가구", "세라믹", "패션", "전통문화", "전통시장", "전통주", "한복", "뷰티",
    "화장품", "섬유",
    # 건설·부동산
    "건설", "건축", "부동산",
    # 물류
    "해운물류", "물류", "유통", "프랜차이즈",
    # 친환경·ESG (산업 한정 키워드로 쓰일 때)
    "그린", "탄소중립", "ESG산업",
    # 모빌리티
    "모빌리티", "자율주행", "드론",
    # 가상자산·블록체인
    "메타버스", "블록체인", "NFT", "Web3", "핀테크",
    # 스마트공장
    "스마트공장",
    # 도시안전·스마트시티 인프라 — sinhon.life와 도메인 완전 불일치
    "CCTV", "영상분석", "이상행동 감지", "군중 밀집", "군중밀집",
    "교통안전 AI", "보행자 경로", "재난예측", "침수 예측", "침수예측",
    "화재 확산", "건축물 붕괴", "도시안전", "도시재난",
    "스마트시티 인프라", "도시인프라", "공공안전", "방범",
]

RED_QUALIFICATION = [
    "OASIS", "이민자", "외국인", "여성전용", "여성창업", "여성기업",
    "제대군인", "자립청년", "소상공인전용",
    "귀농", "귀촌", "다문화가정 전용", "장애인", "북한이탈주민", "탈북",
    "시니어", "중장년", "4050", "경력보유여성",
    "고졸전형", "특성화고", "마이스터고",
    "농업인", "어업인", "임업인",
    "사회적기업가 육성", "협동조합 전용", "마을기업 전용", "자활기업",
]
# ⚠️ "다문화"/"사회적기업"은 단독 키워드로는 RED로 보지 않는다
#    — 공고에 "다문화 대응"·"사회적기업 우대" 정도로 쓰이면 오히려 M08 이벤트 트랙과 매치.
#    단, "다문화가정 전용"·"사회적기업가 육성" 같이 명시적 전용 공고만 RED.

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

# exclude_target(신청 제외 대상) 문구 중 제조업 한정 시그널
EXCLUDE_TARGET_MFG_SIGNALS = [
    "제품의 개발, 생산 및 양산",
    "제품·부품의 개발, 생산 및 양산",
    "제품‧부품의 개발, 생산 및 양산",
    "제품·부품의 개발",
    "부품의 개발",
    "생산 및 양산",
    "제품·부품",
    "하드웨어 한정",
    "제조업 한정",
    "양산을 목적",
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
# ⚠️ TITLE_ONLY 그룹은 title + integrated_name + agency 에서만 매칭한다.
#    apply_target_desc ("예비창업자, 스타트업, 중소기업") 에 걸리면 오탐.
# ══════════════════════════════════════════════════════════════

# title/integrated_name/agency 에서만 매칭 (apply_target_desc 제외)
GREEN_KEYWORDS_TITLE_ONLY = [
    "예비창업패키지", "초기창업패키지",
    "예비창업", "초기창업",
    "모두의 창업", "모두의창업",
    "유니콘 브릿지", "유니콘브릿지",
    "K-Startup 챌린지", "K-스타트업 챌린지",
]

# 인천 관련은 어느 필드에 나오든 GREEN
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

# Haiku 모듈 라우팅 힌트 (카테고리 감지 → 주입할 M-모듈 선택)
CATEGORY_HINT_MAP = {
    "ai": ["AI", "AX", "LLM", "인공지능", "AI바우처", "AI 바우처", "생성형", "딥테크", "클라우드"],
    "content": ["콘텐츠", "미디어", "방송", "1인미디어", "크리에이터", "문체부", "콘텐츠진흥"],
    "incheon": ["인천", "남동구", "인천창조경제혁신센터", "인천TP", "인천스타트업파크", "미추홀", "연수구"],
    "global": ["글로벌", "해외", "K-콘텐츠", "한중싱", "수출", "관광"],
    "social": ["사회적", "공공성", "ESG", "소외계층", "다문화", "여성가족", "복지", "포용"],
    "budget": ["사업화", "초기창업패키지", "예비창업패키지", "초기창업", "예비창업"],
    "rnd": ["R&D", "R&amp;D", "기술개발", "딥테크", "실증"],
}


# ══════════════════════════════════════════════════════════════
# 분류 헬퍼
# ══════════════════════════════════════════════════════════════

def _title_text(item: dict) -> str:
    """title/integrated_name/agency 만 결합 (apply_target_desc 제외)."""
    s = item.get("structured", {}) or {}
    return f"{item.get('title','')} {s.get('integrated_name','')} {item.get('agency','')}"


def _all_text(item: dict) -> str:
    """title + agency + apply_target_desc + integrated_name 결합.
    ⚠️ content/exclude_target은 제외 (너무 많은 false positive).
    """
    s = item.get("structured", {}) or {}
    return (
        f"{item.get('title','')} {item.get('agency','')} "
        f"{s.get('integrated_name','')} {s.get('apply_target_desc','')}"
    )


def detect_category_hints(item: dict) -> list[str]:
    """Haiku 모듈 선택용 카테고리 힌트 리스트."""
    text = _all_text(item)
    s = item.get("structured", {}) or {}
    biz_class = (s.get("biz_class") or "").strip()

    hints = []
    for cat, kws in CATEGORY_HINT_MAP.items():
        if any(kw in text for kw in kws):
            hints.append(cat)

    # biz_class 기반 보강
    if biz_class in GREEN_BIZ_CLASS:
        if "budget" not in hints:
            hints.append("budget")
    if "글로벌" in biz_class or "판로" in biz_class:
        if "global" not in hints:
            hints.append("global")
    if "R&D" in biz_class or "R&amp;D" in biz_class or "기술개발" in biz_class:
        if "rnd" not in hints:
            hints.append("rnd")

    return hints


def _check_struct_recruiting(s: dict) -> tuple[bool, str]:
    if s.get("recruiting") is False:
        return False, "모집 종료 (recruiting=N)"
    return True, ""


def _check_struct_deadline(s: dict) -> tuple[bool, str]:
    end = s.get("end_date") or ""
    if end and end < TODAY:
        return False, f"마감일 경과 ({end})"
    return True, ""


def _check_struct_region(s: dict) -> tuple[bool, str]:
    region = (s.get("region") or "").strip()
    if region in RED_REGIONS_EXCLUSIVE:
        return False, f"지역 한정 ({region})"
    return True, ""


def _check_struct_biz_enyy(s: dict) -> tuple[bool, str]:
    enyy = (s.get("biz_enyy") or "").strip()
    if not enyy:
        return True, "(biz_enyy 비어있음)"
    parts = {p.strip() for p in enyy.split(",") if p.strip()}
    if parts and not (parts & ACCEPTABLE_BIZ_ENYY):
        return False, f"업력 불일치 ({enyy})"
    matched = parts & ACCEPTABLE_BIZ_ENYY
    return True, f"업력 허용 매칭 ({','.join(sorted(matched))})"


def _check_struct_exclude_target(s: dict) -> tuple[bool, str]:
    """신청 제외 대상 체크.
    단순 키워드(대기업/중견기업/공공기관/휴·폐업)와 제조업 한정 시그널을 함께 감지.
    """
    excl = (s.get("exclude_target") or "").strip()
    if not excl:
        return True, ""
    # 명시적 제외 키워드
    for kw in ("대기업", "중견기업", "공공기관 재직자", "휴·폐업", "휴폐업"):
        if kw in excl:
            return False, f"제외대상 명시 ({kw})"
    # 제조업 한정 시그널
    for kw in EXCLUDE_TARGET_MFG_SIGNALS:
        if kw in excl:
            return False, f"제조업 한정 ({kw[:20]}...)"
    return True, ""


def _check_keyword_industry(combined: str) -> tuple[bool, str]:
    for kw in RED_INDUSTRY:
        if kw in combined:
            return False, f"업종 한정 ({kw})"
    return True, ""


def _check_keyword_qualification(combined: str) -> tuple[bool, str]:
    for kw in RED_QUALIFICATION:
        if kw in combined:
            return False, f"자격 한정 ({kw})"
    return True, ""


def _check_keyword_stage(combined: str) -> tuple[bool, str]:
    for kw in RED_STAGE:
        if kw in combined:
            return False, f"단계 불일치 ({kw})"
    return True, ""


def _check_keyword_nature(combined: str) -> tuple[bool, str]:
    for kw in RED_NATURE:
        if kw in combined:
            return False, f"성격 불일치 ({kw})"
    return True, ""


def _check_region_keyword(combined: str, struct_region: str) -> tuple[bool, str]:
    """서울/경기 단독 판정."""
    for kw in RED_SEOUL_FACILITY:
        if kw in combined:
            return False, f"서울 시설/지자체 ({kw})"
    for gu in SEOUL_25_GU:
        if gu in combined:
            return False, f"서울 구 단독 ({gu})"
    for uni in SEOUL_UNIVERSITY:
        if uni in combined:
            return False, f"서울 대학 ({uni})"

    if struct_region in GREEN_REGIONS:
        return True, f"지역 허용 (structured={struct_region})"

    if "서울" in combined:
        for safe in ("오픈이노베이션", "온라인", "비대면", "화상", "전국"):
            if safe in combined:
                return True, f"서울 언급 있으나 {safe} 포함"
        return False, "서울 단독 (인천 미포함)"
    if "경기" in combined and "인천" not in combined:
        return False, "경기 단독 (인천 미포함)"
    return True, ""


# ══════════════════════════════════════════════════════════════
# 메인 분류 로직
# ══════════════════════════════════════════════════════════════

def classify(item: dict) -> tuple[str, dict]:
    """
    공고 1건 분류 → (tier, evidence_dict).
    evidence_dict 스키마:
      {
        "summary_reason": str,             # 한 줄 사유 (legacy note 호환)
        "category_hints": [str, ...],      # 모듈 라우팅용
        "rule_checks": {                   # 표로 렌더링
          "region":        {"pass": bool, "value": str, "detail": str},
          "deadline":      {"pass": bool, "value": str, "detail": str},
          "biz_enyy":      {"pass": bool, "value": str, "detail": str},
          "exclude_target":{"pass": bool, "value": str, "detail": str},
          "industry":      {"pass": bool, "detail": str},
          "qualification": {"pass": bool, "detail": str},
          "stage":         {"pass": bool, "detail": str},
          "nature":        {"pass": bool, "detail": str},
          "region_keyword":{"pass": bool, "detail": str},
          "positive_hit":  {"pass": bool, "detail": str},
        },
        "risk_flags": [                    # 경고 뱃지
          {"type": str, "severity": "low|med|high", "msg": str}
        ]
      }
    """
    title = item.get("title", "")
    agency = item.get("agency", "")
    s = item.get("structured", {}) or {}

    all_combined = _all_text(item)
    title_only = _title_text(item)

    checks = {}
    risks = []

    # ── 1단계: 구조화 RED ──
    ok, detail = _check_struct_recruiting(s)
    checks["recruiting"] = {"pass": ok, "value": str(s.get("recruiting", "?")), "detail": detail}
    if not ok:
        return "red", {
            "summary_reason": detail,
            "category_hints": [],
            "rule_checks": checks,
            "risk_flags": risks,
        }

    ok, detail = _check_struct_deadline(s)
    checks["deadline"] = {"pass": ok, "value": s.get("end_date", ""), "detail": detail}
    if not ok:
        return "red", {
            "summary_reason": detail, "category_hints": [], "rule_checks": checks, "risk_flags": risks,
        }

    ok, detail = _check_struct_region(s)
    checks["region"] = {"pass": ok, "value": s.get("region", ""), "detail": detail or f"region={s.get('region','')}"}
    if not ok:
        return "red", {
            "summary_reason": detail, "category_hints": [], "rule_checks": checks, "risk_flags": risks,
        }

    ok, detail = _check_struct_biz_enyy(s)
    checks["biz_enyy"] = {"pass": ok, "value": s.get("biz_enyy", ""), "detail": detail}
    if not ok:
        return "red", {
            "summary_reason": detail, "category_hints": [], "rule_checks": checks, "risk_flags": risks,
        }

    ok, detail = _check_struct_exclude_target(s)
    checks["exclude_target"] = {"pass": ok, "value": (s.get("exclude_target", "") or "")[:80], "detail": detail}
    if not ok:
        return "red", {
            "summary_reason": detail, "category_hints": [], "rule_checks": checks, "risk_flags": risks,
        }

    # ── 2단계: 키워드 RED ──
    ok, detail = _check_keyword_industry(all_combined)
    checks["industry"] = {"pass": ok, "detail": detail}
    if not ok:
        return "red", {
            "summary_reason": detail, "category_hints": [], "rule_checks": checks, "risk_flags": risks,
        }

    ok, detail = _check_keyword_qualification(all_combined)
    checks["qualification"] = {"pass": ok, "detail": detail}
    if not ok:
        return "red", {
            "summary_reason": detail, "category_hints": [], "rule_checks": checks, "risk_flags": risks,
        }

    ok, detail = _check_keyword_stage(all_combined)
    checks["stage"] = {"pass": ok, "detail": detail}
    if not ok:
        return "red", {
            "summary_reason": detail, "category_hints": [], "rule_checks": checks, "risk_flags": risks,
        }

    ok, detail = _check_keyword_nature(all_combined)
    checks["nature"] = {"pass": ok, "detail": detail}
    if not ok:
        return "red", {
            "summary_reason": detail, "category_hints": [], "rule_checks": checks, "risk_flags": risks,
        }

    ok, detail = _check_region_keyword(all_combined, (s.get("region") or "").strip())
    checks["region_keyword"] = {"pass": ok, "detail": detail}
    if not ok:
        return "red", {
            "summary_reason": detail, "category_hints": [], "rule_checks": checks, "risk_flags": risks,
        }

    # ── 3단계: 긍정 매칭 ──
    region = (s.get("region") or "").strip()
    biz_class = (s.get("biz_class") or "").strip()

    positive_hit = None
    tier = None

    # structured GREEN
    if region in GREEN_REGIONS and biz_class in GREEN_BIZ_CLASS:
        tier = "green"
        positive_hit = f"structured GREEN ({region}/{biz_class})"

    # 키워드 GREEN (title_only 매칭만!)
    if tier is None:
        for kw in GREEN_KEYWORDS_TITLE_ONLY:
            if kw in title_only:
                tier = "green"
                positive_hit = f"핵심 매칭 ({kw}) — title"
                break

    # 인천 GREEN (어느 필드든)
    if tier is None:
        for kw in GREEN_INCHEON:
            if kw in all_combined:
                tier = "green"
                positive_hit = f"인천 매칭 ({kw})"
                break

    # YELLOW
    if tier is None:
        if region in GREEN_REGIONS and biz_class in YELLOW_BIZ_CLASS:
            tier = "yellow"
            positive_hit = f"검토 매칭 ({region}/{biz_class})"

    if tier is None:
        for kw in YELLOW_KEYWORDS:
            if kw in all_combined:
                tier = "yellow"
                positive_hit = f"검토 매칭 ({kw})"
                break

    # ORANGE (AI)
    if tier is None:
        for kw in ORANGE_KEYWORDS:
            if kw in all_combined:
                tier = "orange"
                positive_hit = f"AI 포지셔닝 ({kw})"
                break

    # Default RED
    if tier is None:
        tier = "red"
        positive_hit = "기본 제외 (긍정 매칭 없음)"

    checks["positive_hit"] = {"pass": tier != "red", "detail": positive_hit or ""}

    # ── 4단계: 리스크 플래그 추가 생성 (RED로 안 떨어진 경우에도) ──
    # biz_class가 R&D면 → 하드웨어 공고 가능성 경고
    if "R&D" in biz_class or "R&amp;D" in biz_class or "기술개발" in biz_class:
        risks.append({
            "type": "rnd_hardware_risk",
            "severity": "med",
            "msg": "R&D 공고는 하드웨어·제조 시제품 중심일 수 있음 — 공고문에서 지원대상 상세 확인 필요",
        })
    # title에 '기술개발'/'R&D'가 있으면 강화
    if "R&D" in title or "기술개발" in title:
        risks.append({
            "type": "title_rnd",
            "severity": "high",
            "msg": "제목에 R&D/기술개발 포함 — SaaS/플랫폼 성격과 부합하지 않을 수 있음",
        })
    # exclude_target 내용이 길면 위험 플래그
    excl = (s.get("exclude_target") or "").strip()
    if excl and len(excl) > 100:
        risks.append({
            "type": "exclude_target_long",
            "severity": "low",
            "msg": f"신청 제외 대상이 길게 기술됨 ({len(excl)}자) — 본문 정독 필수",
        })
    # apply_target에 '1인 창조기업' 외에 '대학/연구기관'만 있으면 B2C 플랫폼과 거리
    apply_target = (s.get("apply_target") or "")
    if apply_target and "일반기업" not in apply_target and "1인 창조기업" not in apply_target:
        risks.append({
            "type": "apply_target_narrow",
            "severity": "med",
            "msg": f"신청 가능 대상이 좁음 ({apply_target[:40]}) — 엑스컴 자격 재확인",
        })

    category_hints = detect_category_hints(item)

    return tier, {
        "summary_reason": positive_hit or "",
        "category_hints": category_hints,
        "rule_checks": checks,
        "risk_flags": risks,
    }


# ══════════════════════════════════════════════════════════════
# 풀 머지 / 입출력 (standalone 실행용 — update.py 경로 아님)
# ══════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("Usage: python classify.py <crawl_results.json> [existing_pool.json] > recommendations.json",
              file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        crawled = json.load(f)

    existing_pool = {
        "schema_version": 3, "last_updated": "",
        "items": [], "red_count_today": 0, "reds_today": []
    }
    if len(sys.argv) >= 3:
        try:
            with open(sys.argv[2], "r", encoding="utf-8") as f:
                existing_pool = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    existing_by_sn = {
        it.get("pbancSn", ""): it for it in existing_pool.get("items", []) if it.get("pbancSn")
    }

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

    for it in kept_items:
        tier, ev = classify(it)
        it["_tier"] = tier
        it["_evidence"] = ev

    new_items = []
    for it in all_candidates:
        sn = it.get("pbancSn", "")
        tier, ev = classify(it)
        if sn in existing_by_sn:
            existing_by_sn[sn]["last_seen"] = TODAY
            existing_by_sn[sn]["_tier"] = tier
            existing_by_sn[sn]["_evidence"] = ev
            if it.get("deadline"):
                existing_by_sn[sn]["deadline"] = it["deadline"]
            if it.get("structured"):
                existing_by_sn[sn]["structured"] = it["structured"]
        else:
            it["first_seen"] = TODAY
            it["last_seen"] = TODAY
            it["_tier"] = tier
            it["_evidence"] = ev
            new_items.append(it)

    final_items = []
    red_count = 0
    reds_list = []
    new_added = []

    for it in kept_items + new_items:
        tier = it.pop("_tier", "red")
        evidence = it.pop("_evidence", {})
        reason = evidence.get("summary_reason", "")
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
            it["evidence"] = evidence
            final_items.append(it)
            if it.get("first_seen") == TODAY:
                new_added.append(it.get("title", ""))

    tier_order = {"green": 0, "yellow": 1, "orange": 2}
    final_items.sort(key=lambda x: (
        tier_order.get(x.get("tier"), 9),
        x.get("deadline") or "9999-99-99",
    ))

    result = {
        "schema_version": 4,
        "last_updated": TODAY,
        "red_count_today": red_count,
        "reds_today": reds_list[:100],
        "items": final_items,
        "_meta": {
            "version": "v7",
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
