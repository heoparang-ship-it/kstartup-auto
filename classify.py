#!/usr/bin/env python3
"""
K-Startup 공고 자동 분류기 v9.0 (profile.md v4 기반)

핵심 설계:
1. 생애주기 7단계 화이트리스트 (L1~L7) + L0 범용 플랫폼
2. 도메인 네거티브 하드 차단 (9카테고리 × 2+ hit → 무조건 RED)
3. 트리플 엔티티 매트릭스 (E1 허파랑 개인 / E2 XCom 법인 / E3 이영림 대구)
4. 엔티티별 독립 tier 평가 → best_entity/best_tier 자동 산출
5. green → yellow 감사 강등 (audit_flags)
6. nogo_history.json 피드백 루프

출력 스키마:
{
  "pbancSn": "...", "title": "...", "tier": "green|yellow|orange|red",
  "best_entity": "heoparang_personal|xcom_corp|younglim_daegu|none",
  "best_tier": "green|yellow|orange|red",
  "domain": {
    "whitelisted": true,
    "hit_layers": ["L2_허니문", "L3_콘텐츠"],
    "negative_flags": []
  },
  "entities": {
    "heoparang_personal": {"tier": "yellow", "reason": "...", "audit_flags": [...]},
    "xcom_corp":          {"tier": "green",  "reason": "...", "audit_flags": []},
    "younglim_daegu":     {"tier": "red",    "reason": "지역 미스매치", "audit_flags": []}
  },
  "rationale_short": "대구 예비창업 전용 + 웨딩콘텐츠 레이어 매칭"
}
"""
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y-%m-%d")
VERSION = "9.0"
KEYWORDS_VERSION = "v4"

# ══════════════════════════════════════════════════════════════
# 생애주기 7단계 화이트리스트 (L1~L7)
# ══════════════════════════════════════════════════════════════

LIFECYCLE_DOMAINS = {
    "L1_결혼준비":     ["웨딩", "예식", "드레스", "스튜디오", "혼수", "웨딩플래닝",
                       "결혼준비", "신혼", "혼례", "예단"],
    "L2_허니문관광":   ["허니문", "신혼여행", "국내관광", "웰니스관광", "로컬관광",
                       "관광두레", "관광벤처", "관광스타트업", "지역관광", "체험관광"],
    "L3_콘텐츠미디어": ["웨딩콘텐츠", "K-웨딩", "라이프스타일", "크리에이터",
                       "1인미디어", "콘텐츠IP", "미디어커머스", "쇼츠", "숏폼"],
    "L4_이벤트체험":   ["리마인드웨딩", "결혼기념", "이벤트기획", "체험상품",
                       "로컬체험", "팝업"],
    "L5_출산육아":     ["임신", "출산지원", "육아지원", "영유아", "영유아 보육",
                       "가족친화", "다자녀", "신생아", "난임", "임산부"],
    "L6_주거":         ["신혼주거", "신혼청약", "주거복지", "주거안정",
                       "신혼부부 주택", "주거지원"],
    "L7_금융":         ["신혼부부 대출", "신혼부부 금융", "태아보험", "가족보험",
                       "생애주기 금융", "웨딩론"],
}

L0_PLATFORM_GENERIC = [
    "B2C", "플랫폼", "SaaS", "모바일앱", "PWA", "커머스",
    "라이프스타일 서비스", "개인화", "AI 비서", "Claude API", "LLM 서비스",
]

# ══════════════════════════════════════════════════════════════
# 도메인 네거티브 하드 (2+ hit → 무조건 RED, 엔티티 무관)
# ══════════════════════════════════════════════════════════════

DOMAIN_NEGATIVE_HARD = {
    "도시안전·치안": ["도시안전", "치안", "이상행동 감지", "CCTV", "영상분석",
                     "군중관리", "재난안전", "안전 신기술", "안전신기술",
                     "산업안전", "시설안전", "교통안전"],
    "제조·공정":     ["스마트팩토리", "공정혁신", "제조혁신", "스마트제조",
                     "MES", "뿌리산업", "금형", "공작기계"],
    "의료기기·임상": ["의료기기", "임상시험", "GMP", "식약처 허가", "KC 인증",
                     "ISO 13485"],
    "바이오·신약":   ["신약개발", "전임상", "바이오시밀러", "유전체", "생물의약"],
    "농수축임":      ["스마트팜", "양식", "축산 ICT", "임업", "작물 재배"],
    "국방·군수":     ["국방", "방산", "무기체계", "군수"],
    "건설·토목":     ["토목 시공", "건설기술 R&D", "건축설계", "플랜트"],
    "에너지·발전":   ["원전", "송전", "발전소", "재생에너지 발전"],
    "관광B2B무관":   ["관광호텔", "MICE 시설", "항공물류", "크루즈", "카지노"],
    "TRL증빙필수":   ["TRL 5 이상", "TRL 6", "TRL 7", "시험성적서 필수",
                     "KC 인증 필수"],
}

# ══════════════════════════════════════════════════════════════
# 엔티티 3종 자격 규칙
# ══════════════════════════════════════════════════════════════

ENTITY_CONFIG = {
    "heoparang_personal": {
        "display_name": "허파랑 개인",
        "home_region_keywords": ["전국", "인천", "수도권"],
        "home_agencies": ["인천", "창업진흥원", "중소벤처기업부", "K-Startup"],
        "allowed_stages": ["예비창업"],
        "blocked_stages": ["법인 필수", "사업자등록 필수", "5년 이상 업력",
                          "7년 이내 업력", "초기창업"],
        "strong_triggers": ["예비창업패키지", "예창패", "모두의 창업",
                           "청년창업사관학교"],
        "regional_strong": ["인천창조경제혁신센터", "인천테크노파크",
                           "인천스타트업파크", "남동구 청년창업",
                           "인천경제자유구역", "ICCE"],
    },
    "xcom_corp": {
        "display_name": "XCom 법인",
        "home_region_keywords": ["전국", "인천", "수도권"],
        "home_agencies": ["인천", "창업진흥원", "중소벤처기업부"],
        "allowed_stages": ["초기창업", "창업 3년 이내", "창업 7년 이내"],
        "blocked_stages": ["예비창업 한정", "7년 초과", "대기업", "스케일업"],
        "strong_triggers": ["초기창업패키지", "초창패", "TIPS", "프리팁스",
                           "K-Startup 챌린지", "유니콘 브릿지"],
        "regional_strong": ["인천창조경제혁신센터", "인천테크노파크",
                           "인천스타트업파크", "남동구 청년창업",
                           "인천경제자유구역", "ICCE"],
    },
    "younglim_daegu": {
        "display_name": "이영림 대구",
        "home_region_keywords": ["전국", "대구", "경북", "영남"],
        "home_agencies": ["대구", "경북"],
        "allowed_stages": ["예비창업"],
        "blocked_stages": ["법인 필수", "사업자등록 필수", "인천 전용",
                          "수도권 전용", "서울 전용", "5년 이상 업력"],
        "strong_triggers": ["예비창업패키지", "예창패", "모두의 창업",
                           "청년창업사관학교", "여성창업", "청년창업"],
        "regional_strong": ["대구창조경제혁신센터", "대구테크노파크",
                           "대구디지털산업진흥원", "DIP",
                           "경북창조경제혁신센터", "경북TP"],
    },
}

# ══════════════════════════════════════════════════════════════
# 서울·비거점 지역 리스트 (region mismatch 판정)
# ══════════════════════════════════════════════════════════════

SEOUL_FACILITY = [
    "서울창업허브", "서울 입주", "성수 입주", "마포 입주", "강남 입주",
    "서울 소재", "서초 소재", "성수동", "역삼동", "판교", "성남", "파주",
    "서울숲", "합정", "홍대입구", "신촌", "종로", "중구", "용산",
]
SEOUL_25_GU = [
    "강남구", "서초구", "관악구", "은평구", "노원구", "동작구",
    "성북구", "성동구", "마포구", "용산구", "종로구",
    "동대문구", "광진구", "서대문구", "양천구",
    "영등포구", "구로구", "금천구", "도봉구",
    "강북구", "중랑구", "강서구", "강동구", "송파구",
]
# 비수도권 지역명 (E1·E2 기준으로 불허, E3는 대구·경북 포함되므로 별도)
# 경기권 일부 도시도 "해당 시 전용" 공고라면 불허로 본다
NON_METRO_REGIONS = [
    "부산", "대전", "광주", "울산", "대구", "강원", "충북", "충남",
    "전북", "전남", "경남", "경북", "제주", "세종", "비수도권",
    "거제", "창원", "김해", "양산", "진주", "통영",
    "포항", "구미", "경주", "안동", "영주", "상주",
    "전주", "익산", "군산", "여수", "순천", "목포", "광양",
    "천안", "아산", "청주", "충주", "제천", "당진", "서산", "공주",
    "춘천", "원주", "강릉", "속초", "동해", "삼척",
    "제주시", "서귀포",
]
# E3 (이영림 대구) 기준 비거점
NON_DAEGU_REGIONS = [
    "부산", "대전", "광주", "울산", "강원", "충북", "충남", "전북", "전남",
    "경남", "제주", "세종", "비수도권",
    "인천", "수원", "안양", "안산", "화성", "평택", "시흥", "성남", "용인",
    "과천", "광명", "군포", "의왕", "부천", "구리", "남양주",
    "김포", "고양", "양주", "의정부", "하남", "파주",
    "춘천", "원주", "강릉", "속초",
    "전주", "익산", "군산", "여수", "순천", "목포",
]
# 경기권 자체 지역 한정 공고 (E1·E2 기준 — 수도권이지만 "해당 시 거주자"로 제한)
GYEONGGI_LOCAL_ONLY = [
    "과천시", "양주시", "구리시", "광명시", "군포시", "의왕시",
    "용인시", "성남시", "부천시", "남양주시", "하남시", "파주시",
    "안성시", "이천시", "여주시", "연천", "가평", "양평",
]

# ══════════════════════════════════════════════════════════════
# Audit (green → yellow 강등) 키워드
# ══════════════════════════════════════════════════════════════

AUDIT_EVENT = ["설명회", "간담회", "포럼", "세미나", "기념식",
               "시상식", "성과공유회"]
AUDIT_DISGUISED = ["인증 취득 지원", "기술임치 계약", "언론 보도 지원",
                   "PR 지원", "특허 취득 지원"]
AUDIT_NARROW = ["재학 중인 대학", "시민만", "구민만", "여성만",
                "외국인등록증 소지자", "체류자격 F-", "탈북", "다문화 한정"]

# ══════════════════════════════════════════════════════════════
# 분류 함수
# ══════════════════════════════════════════════════════════════

def scan_lifecycle(text: str) -> list[str]:
    """생애주기 레이어 hit 스캔. [L2_허니문관광, L3_콘텐츠미디어] 형태 반환."""
    hits = []
    for layer, keywords in LIFECYCLE_DOMAINS.items():
        for kw in keywords:
            if kw in text:
                hits.append(layer)
                break
    return hits


def scan_l0(text: str) -> bool:
    """L0 범용 플랫폼 키워드 hit 여부."""
    return any(kw in text for kw in L0_PLATFORM_GENERIC)


def scan_negative(text: str) -> list[str]:
    """도메인 네거티브 카테고리 hit. 2+ hit 시 HARD RED."""
    hits = []
    for category, keywords in DOMAIN_NEGATIVE_HARD.items():
        count = sum(1 for kw in keywords if kw in text)
        if count >= 2:
            hits.append(category)
    return hits


def infer_region_from_agency(agency: str) -> str | None:
    """agency 텍스트에서 지역명 추출. structured.region이 '전국'이어도 실제로는 지역 한정인 경우 감지."""
    agency_region_hints = {
        "인천": ["인천창조경제혁신센터", "인천테크노파크", "인천스타트업파크",
                "인천경제자유구역", "IFEZ", "ICCE", "인천시", "남동구", "연수구"],
        "대구": ["대구창조경제혁신센터", "대구테크노파크", "대구디지털산업진흥원",
                "DIP", "대구시", "수성구", "달성군"],
        "경북": ["경북창조경제혁신센터", "경북TP", "경북테크노파크"],
        "서울": ["서울산업진흥원", "SBA", "서울창업허브", "서울특별시",
                "서울시", "서초구", "강남구", "성동구", "마포구",
                "서울관광재단", "서울경제진흥원", "서울시설공단",
                "서울신용보증재단", "서울창조경제혁신센터",
                "종로여성인력개발센터", "서울여성발전센터"],
        "부산": ["부산창조경제혁신센터", "부산TP", "부산테크노파크", "부산시"],
        "대전": ["대전창조경제혁신센터", "대전TP", "대전테크노파크", "대전시",
                "연구개발특구진흥재단", "KAIST"],
        "광주": ["광주창조경제혁신센터", "광주TP", "광주테크노파크", "광주시"],
        "울산": ["울산창조경제혁신센터", "울산TP", "울산테크노파크", "울산시"],
        "세종": ["세종창조경제혁신센터", "세종시"],
        "제주": ["제주창조경제혁신센터", "제주TP", "제주도"],
        "경기": ["경기창조경제혁신센터", "경기TP", "경기테크노파크",
                "경기도경제과학진흥원", "경기콘텐츠진흥원", "경기도",
                "성남시", "수원시", "안양시", "안산시", "화성시", "평택시",
                "시흥시", "김포시", "고양시", "부천시", "구리시", "과천시",
                "용인시", "의왕시", "광명시", "군포시", "남양주시", "하남시",
                "차세대융합기술연구원"],
        "강원": ["강원창조경제혁신센터", "강원TP", "강원도"],
        "충북": ["충북창조경제혁신센터", "충북TP", "청주시"],
        "충남": ["충남창조경제혁신센터", "충남TP", "천안시", "아산시"],
        "전북": ["전북창조경제혁신센터", "전북TP", "전주시", "익산시"],
        "전남": ["전남창조경제혁신센터", "전남TP", "여수시", "순천시"],
        "경남": ["경남창조경제혁신센터", "경남TP", "창원시", "김해시", "양산시",
                "진주시", "거제시", "통영시"],
    }
    for region, hints in agency_region_hints.items():
        for hint in hints:
            if hint in agency:
                return region
    return None


def evaluate_entity_region(entity_key: str, text: str,
                            structured: dict,
                            agency_top: str = "") -> tuple[str, str]:
    """엔티티 기준 지역 평가. Returns (level, reason)."""
    config = ENTITY_CONFIG[entity_key]
    region = structured.get("region", "")
    # agency는 item 레벨 우선, structured fallback
    agency = agency_top or structured.get("agency", "") or \
             structured.get("supervising_agency", "") or \
             structured.get("exec_agency", "")

    # 0. agency 기반 강제 추론 (structured.region이 "전국"이어도 agency로 뒤집음)
    inferred = infer_region_from_agency(agency)
    if inferred:
        if entity_key in ["heoparang_personal", "xcom_corp"]:
            # E1·E2는 인천 또는 전국만 OK
            if inferred == "인천":
                return "green", f"agency 기반 인천 매칭 ({agency})"
            if inferred == "서울":
                return "red", f"agency 기반 서울 전용 ({agency})"
            if inferred != "인천":
                return "red", f"agency 기반 {inferred} 전용 ({agency})"
        elif entity_key == "younglim_daegu":
            # E3는 대구·경북만 OK
            if inferred in ["대구", "경북"]:
                return "green", f"agency 기반 {inferred} 매칭 ({agency})"
            else:
                return "red", f"agency 기반 {inferred} 전용 — 대구·경북 아님"

    # 1. 거점 기관 강 매칭
    for kw in config["regional_strong"]:
        if kw in text:
            return "green", f"거점 기관 매칭 ({kw})"

    # 2. 경기권 자체 지역 한정 체크 (E1·E2 모두 red — 인천 아님)
    if entity_key in ["heoparang_personal", "xcom_corp"]:
        for kw in GYEONGGI_LOCAL_ONLY:
            if kw in text:
                return "red", f"경기권 자체 지역 한정 ({kw})"

    # 3. home_region_keywords 매칭
    for kw in config["home_region_keywords"]:
        if kw in region or kw in text:
            # 서울 단독 여부 체크 (E1/E2는 서울 단독이면 미스매치)
            if entity_key in ["heoparang_personal", "xcom_corp"]:
                for seoul_kw in SEOUL_FACILITY + SEOUL_25_GU:
                    if seoul_kw in text:
                        return "red", f"서울 단독 ({seoul_kw})"
                return "green", f"지역 매칭 ({kw})"
            if entity_key == "younglim_daegu":
                return "green", f"지역 매칭 ({kw})"

    # 4. 특정 지역 키워드 (대덕·연구개발특구 = 대전권)
    specific_region_keywords = {
        "대전": ["대덕특구", "대덕구", "대전 소재", "연구개발특구진흥재단"],
        "세종": ["세종 소재", "세종시 "],
    }
    for reg, kws in specific_region_keywords.items():
        for kw in kws:
            if kw in text:
                if entity_key in ["heoparang_personal", "xcom_corp"]:
                    return "red", f"{reg} 단독 ({kw})"
                if entity_key == "younglim_daegu":
                    return "red", f"대구·경북 미포함 ({kw})"

    # 5. 미스매치
    if entity_key == "younglim_daegu":
        for kw in NON_DAEGU_REGIONS:
            if kw in text:
                return "red", f"대구·경북 미포함 ({kw})"
    else:  # E1, E2
        for kw in NON_METRO_REGIONS:
            if kw in text:
                return "red", f"비수도권 단독 ({kw})"
        for kw in SEOUL_FACILITY + SEOUL_25_GU:
            if kw in text:
                return "red", f"서울 단독 ({kw})"

    return "yellow", "지역 정보 모호"


def evaluate_entity_stage(entity_key: str, text: str,
                           structured: dict) -> tuple[str, str]:
    """엔티티 기준 단계(업력) 평가."""
    config = ENTITY_CONFIG[entity_key]
    biz_enyy = structured.get("biz_enyy", "")
    combined = text + " " + biz_enyy

    # 실격 키워드 체크
    for kw in config["blocked_stages"]:
        if kw in combined:
            return "red", f"단계 불일치 ({kw})"

    # 허용 키워드 체크
    for kw in config["allowed_stages"]:
        if kw in combined:
            return "green", f"단계 매칭 ({kw})"

    # biz_enyy 기반 추론
    if entity_key == "heoparang_personal" or entity_key == "younglim_daegu":
        if "예비창업자" in biz_enyy:
            return "green", "예비창업 자격"
        if biz_enyy and "예비창업자" not in biz_enyy:
            return "yellow", "예비창업 자격 모호"
    elif entity_key == "xcom_corp":
        if any(kw in biz_enyy for kw in ["1년미만", "2년미만", "3년미만"]):
            return "green", "초기창업 범위"
        if "예비창업자" in biz_enyy and not any(
            kw in biz_enyy for kw in ["1년미만", "2년미만", "3년미만"]):
            return "yellow", "예비창업 전용 가능성"

    return "yellow", "단계 정보 부족"


def run_audit(entity_key: str, text: str, structured: dict) -> list[str]:
    """green 잠정 판정된 엔티티에 대해 감사 강등 사유 스캔."""
    flags = []
    agency = structured.get("agency", "")
    apply_target_desc = structured.get("apply_target_desc", "")
    exclude_target = structured.get("exclude_target", "")
    integrated_name = structured.get("integrated_name", "")

    # local_agency_suspect: (재)·진흥원·TP 등, 단 해당 엔티티 거점 기관은 면제
    config = ENTITY_CONFIG[entity_key]
    suspect_patterns = ["(재)", "재단법인", "진흥원", "테크노파크",
                        "창조경제혁신센터", "창업보육센터", "청년센터"]
    is_exempt = any(rs in agency for rs in config["regional_strong"]) or \
                "창업진흥원" in agency or "NIPA" in agency
    if not is_exempt:
        for pat in suspect_patterns:
            if pat in agency:
                flags.append(f"local_agency_suspect:{pat}")
                break

    # event_suspect
    combined_event = integrated_name + " " + text
    for kw in AUDIT_EVENT:
        if kw + " 개최" in combined_event or kw in integrated_name:
            flags.append(f"event_suspect:{kw}")
            break

    # narrow_target_suspect
    combined_target = apply_target_desc + " " + exclude_target
    for kw in AUDIT_NARROW:
        if kw in combined_target:
            flags.append(f"narrow_target_suspect:{kw}")
            break

    # disguised_funding
    for kw in AUDIT_DISGUISED:
        if kw in text:
            flags.append(f"disguised_funding:{kw}")
            break

    return flags


def evaluate_entity(entity_key: str, text: str, structured: dict,
                     lifecycle_hits: list[str], l0_hit: bool,
                     agency_top: str = ""
                    ) -> dict:
    """엔티티 1개에 대한 완전한 평가."""
    config = ENTITY_CONFIG[entity_key]

    # 강 매칭 트리거
    strong_hit = None
    for kw in config["strong_triggers"] + config["regional_strong"]:
        if kw in text:
            strong_hit = kw
            break

    # 지역·단계 평가
    region_level, region_reason = evaluate_entity_region(
        entity_key, text, structured, agency_top=agency_top)
    stage_level, stage_reason = evaluate_entity_stage(entity_key, text, structured)

    # red 결정: 지역·단계 중 하나라도 red면 해당 엔티티 red
    if region_level == "red":
        return {
            "tier": "red",
            "reason": region_reason,
            "audit_flags": [],
            "strong_hit": strong_hit,
        }
    if stage_level == "red":
        return {
            "tier": "red",
            "reason": stage_reason,
            "audit_flags": [],
            "strong_hit": strong_hit,
        }

    # 도메인 화이트리스트 체크
    total_domain_hits = len(lifecycle_hits) + (1 if l0_hit else 0)

    # tier 결정
    # 최우선: 강 매칭
    if strong_hit and region_level == "green" and stage_level in ["green", "yellow"]:
        tier = "green"
        reason = f"강 매칭 ({strong_hit}) + {region_reason}"
    # 지역 green + 라이프사이클 매칭 (강도별)
    elif region_level == "green" and stage_level == "green" and len(lifecycle_hits) >= 2:
        tier = "green"
        reason = f"{region_reason} + 라이프사이클 {len(lifecycle_hits)}개"
    elif region_level == "green" and stage_level == "green" and len(lifecycle_hits) == 1:
        tier = "yellow"
        reason = f"{region_reason} + 라이프사이클 1개"
    elif region_level == "green" and stage_level == "yellow" and len(lifecycle_hits) >= 1:
        tier = "yellow"
        reason = f"{region_reason} + 라이프사이클 {len(lifecycle_hits)}개 + 단계 모호"
    # 지역 green + L0만 (lifecycle 0): 약한 매칭 → orange
    elif region_level == "green" and not lifecycle_hits and l0_hit:
        tier = "orange"
        reason = f"{region_reason} + L0 단독 (약한 매칭)"
    # 지역 green + lifecycle 0 + L0 0: 도메인 미스매치
    elif region_level == "green" and not lifecycle_hits and not l0_hit:
        tier = "orange"
        reason = f"{region_reason} / 도메인 미스매치"
    # 지역 yellow: lifecycle 있어야 yellow
    elif region_level == "yellow":
        if lifecycle_hits:
            tier = "yellow"
            reason = f"{region_reason} / 라이프사이클 {len(lifecycle_hits)}개"
        else:
            tier = "orange"
            reason = f"{region_reason} / L0 단독 또는 도메인 미스매치"
    # fallback
    elif total_domain_hits == 0:
        tier = "orange"
        reason = "도메인 미스매치"
    else:
        tier = "yellow"
        reason = f"부분 매칭 ({region_reason})"

    # green 감사 강등
    audit_flags = []
    if tier == "green":
        audit_flags = run_audit(entity_key, text, structured)
        if audit_flags:
            tier = "yellow"
            reason = f"{reason} → 감사 강등 ({len(audit_flags)}건)"

    return {
        "tier": tier,
        "reason": reason,
        "audit_flags": audit_flags,
        "strong_hit": strong_hit,
    }


TIER_RANK = {"green": 4, "yellow": 3, "orange": 2, "red": 1}


def classify(item: dict, nogo_patterns: list[str] = None) -> dict:
    """공고 1건 완전 분류. v4 스키마 반환."""
    nogo_patterns = nogo_patterns or []

    title = item.get("title", "")
    agency = item.get("agency", "")
    structured = item.get("structured", {}) or {}
    content = structured.get("content", "")
    integrated_name = structured.get("integrated_name", "")
    apply_target_desc = structured.get("apply_target_desc", "")
    biz_class = structured.get("biz_class", "")

    # 전체 검색 텍스트
    text = " ".join([title, agency, content, integrated_name,
                     apply_target_desc, biz_class])

    # nogo 패턴 매칭 (사용자 피드백 루프)
    nogo_hit = None
    for pattern in nogo_patterns:
        if pattern and pattern in text:
            nogo_hit = pattern
            break

    # 1. 도메인 네거티브 하드 체크
    negative_flags = scan_negative(text)
    if negative_flags:
        return {
            "tier": "red",
            "best_entity": "none",
            "best_tier": "red",
            "domain": {
                "whitelisted": False,
                "hit_layers": [],
                "negative_flags": negative_flags,
            },
            "entities": {},
            "rationale_short": f"도메인 네거티브: {', '.join(negative_flags)}",
            "nogo_match": nogo_hit,
        }

    # 2. 라이프사이클 + L0 스캔
    lifecycle_hits = scan_lifecycle(text)
    l0_hit = scan_l0(text)
    whitelisted = bool(lifecycle_hits) or l0_hit

    # 3. 만료 체크
    deadline = item.get("deadline", "")
    if deadline and deadline < TODAY:
        return {
            "tier": "red",
            "best_entity": "none",
            "best_tier": "red",
            "domain": {
                "whitelisted": whitelisted,
                "hit_layers": lifecycle_hits,
                "negative_flags": [],
            },
            "entities": {},
            "rationale_short": f"마감일 경과 ({deadline})",
            "nogo_match": nogo_hit,
        }

    # 4. 도메인 화이트리스트 미통과 → RED (엔티티 평가 스킵)
    if not whitelisted:
        return {
            "tier": "red",
            "best_entity": "none",
            "best_tier": "red",
            "domain": {
                "whitelisted": False,
                "hit_layers": [],
                "negative_flags": [],
            },
            "entities": {},
            "rationale_short": "생애주기 레이어 매칭 0개 + 범용 플랫폼 키워드 없음",
            "nogo_match": nogo_hit,
        }

    # 5. 엔티티 3종 독립 평가
    entities = {}
    for entity_key in ENTITY_CONFIG.keys():
        entities[entity_key] = evaluate_entity(
            entity_key, text, structured, lifecycle_hits, l0_hit,
            agency_top=agency
        )

    # 6. best_entity / best_tier
    best_entity = max(entities.keys(), key=lambda k: TIER_RANK[entities[k]["tier"]])
    best_tier = entities[best_entity]["tier"]

    # 7. nogo 패턴 hit 시 tier 1단계 하향
    if nogo_hit and best_tier in ["green", "yellow"]:
        demoted = {"green": "yellow", "yellow": "orange"}[best_tier]
        best_tier = demoted

    # 8. 간단 요약
    layer_str = ", ".join(l.split("_", 1)[1] if "_" in l else l
                          for l in lifecycle_hits[:3])
    rationale_short = (
        f"{ENTITY_CONFIG[best_entity]['display_name']} 명의 추천 / "
        f"레이어: {layer_str or 'L0 범용'} / "
        f"사유: {entities[best_entity]['reason']}"
    )

    return {
        "tier": best_tier,
        "best_entity": best_entity,
        "best_tier": best_tier,
        "domain": {
            "whitelisted": True,
            "hit_layers": lifecycle_hits,
            "negative_flags": [],
            "l0_generic": l0_hit,
        },
        "entities": entities,
        "rationale_short": rationale_short,
        "nogo_match": nogo_hit,
    }


# ══════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════

def keyword_counts() -> dict:
    """profile.md와 싱크 확인용 키워드 카운트."""
    return {
        **{f"LIFECYCLE_{layer}": len(kws)
           for layer, kws in LIFECYCLE_DOMAINS.items()},
        "L0_PLATFORM_GENERIC": len(L0_PLATFORM_GENERIC),
        **{f"NEG_DOMAIN_{cat.replace('·', '')}": len(kws)
           for cat, kws in DOMAIN_NEGATIVE_HARD.items()},
        **{f"ENTITY_{k}_strong": len(v["strong_triggers"])
           for k, v in ENTITY_CONFIG.items()},
    }


def load_nogo_patterns(nogo_path: Path) -> list[str]:
    """nogo_history.json에서 패턴 로드."""
    if not nogo_path.exists():
        return []
    try:
        data = json.loads(nogo_path.read_text(encoding="utf-8"))
        patterns = []
        for entry in data.get("nogo_entries", []):
            patterns.extend(entry.get("patterns", []))
        return patterns
    except Exception:
        return []


def main():
    if len(sys.argv) < 2:
        print("Usage: python classify_v9.py <input.json> [existing.json]",
              file=sys.stderr)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    existing_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else None

    with input_path.open(encoding="utf-8") as f:
        source = json.load(f)

    # 기존 풀이 있으면 결합 (items 필드 + reds_today의 정보 유지)
    existing_items = []
    if existing_path and existing_path.exists():
        with existing_path.open(encoding="utf-8") as f:
            existing_pool = json.load(f)
        existing_items = existing_pool.get("items", [])

    # source 스키마 정규화
    if isinstance(source, list):
        candidates = source
    else:
        candidates = source.get("items", [])

    # 기존 풀 + 신규 후보 통합
    all_items = {}
    for item in existing_items + candidates:
        sn = str(item.get("pbancSn", ""))
        if sn:
            all_items[sn] = item

    # nogo 패턴 로드
    nogo_path = Path(existing_path.parent if existing_path else ".") / "nogo_history.json"
    nogo_patterns = load_nogo_patterns(nogo_path)

    # 분류
    final_items = []
    reds = []
    for sn, item in all_items.items():
        verdict = classify(item, nogo_patterns=nogo_patterns)
        item["tier"] = verdict["tier"]
        item["best_entity"] = verdict["best_entity"]
        item["best_tier"] = verdict["best_tier"]
        item["domain"] = verdict["domain"]
        item["entities"] = verdict["entities"]
        item["rationale_short"] = verdict["rationale_short"]
        item["nogo_match"] = verdict.get("nogo_match")

        if verdict["tier"] == "red":
            reds.append({
                "pbancSn": sn,
                "title": item.get("title", ""),
                "agency": item.get("agency", ""),
                "reason": verdict["rationale_short"],
                "negative_flags": verdict["domain"]["negative_flags"],
            })
        else:
            final_items.append(item)

    # 통계
    from collections import Counter
    tier_stats = Counter(i["tier"] for i in final_items)
    entity_stats = Counter(i.get("best_entity", "none") for i in final_items)

    result = {
        "schema_version": 4,
        "last_updated": TODAY,
        "red_count_today": len(reds),
        "reds_today": reds[:200],
        "items": final_items,
        "_meta": {
            "version": VERSION,
            "keywords_version": KEYWORDS_VERSION,
            "keyword_counts": keyword_counts(),
            "stats": {
                "total_pool": len(final_items),
                "tier": dict(tier_stats),
                "best_entity": dict(entity_stats),
                "red_excluded": len(reds),
            },
        },
    }

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
