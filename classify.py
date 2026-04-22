#!/usr/bin/env python3
"""
K-Startup 공고 자동 분류기 v8.3 — 3티어 전원 수용 + 1순위 정밀화 + 감사 루틴
═════════════════════════════════════════════════════════════════════════════

v7 → v8 → v8.3 변경점:
1. **red 제거**: 마감·비모집만 실제 필터, 나머지는 전원 green/yellow/orange에 배치.
2. **1순위(green) 엄격화**: 지역·단계·업종·자금성격·자격 5축이 모두 부합 + 긍정 키워드 매칭된 공고만.
3. **3순위(orange) 확장**: 업종 한정·서울 단독·여성전용 등도 orange에 수용.
   각 항목에 exclusion_flags[]로 "왜 3순위인지" 구조화해 카드에서 표시.
4. **axis_scores**: 5축 점수(green/yellow/orange) 반환 → UI에서 배지 렌더링.
5. **v8.3 NEW — green 티어 감사 루틴 (_audit_green_tier)**:
   1순위 확정 전 agency / integrated_conditions / exclude_target / apply_target_desc를
   한 번 더 스캔해 지자체 산하 의심 기관·행사성 공고·협소 대상을 적발하면 yellow로 강등.
   → classify() evidence에 audit_flags[] 필드로 기록. green "오염" 재발 방지.
6. **v8.3 NEW — Region 축 agency 조기 차단**:
   _score_region 상단에서 agency의 (재)·○○진흥원·테크노파크·경제진흥원 패턴 +
   비수도권 지역명을 조기 감지해 structured.region='전국' 값을 덮어씀. 인천 제외.
7. **v8.3 NEW — 버전 스탬프**:
   CLASSIFY_VERSION / KEYWORDS_VERSION 상수 + 출력 _meta에 keyword_counts 기록
   → profile.md와의 동기화 여부를 기계적으로 검증 가능.

classify() 반환 스키마:
  (tier, {
    summary_reason, category_hints,
    rule_checks (backward-compat),
    risk_flags,
    axis_scores: {region, stage, industry, nature, qualification},
    exclusion_flags: [{axis, severity, msg}],
    audit_flags: [{type, msg}],  # v8.3 신규
    tier_logic: "green/yellow/orange 결정 이유 한줄",
    classify_version: "v8.3",    # v8.3 신규
  })

입력: crawl_v6.py / update.py가 넘기는 item dict (structured 포함)
출력: classify()는 (tier, evidence) 튜플. 스크립트로 돌리면 recommendations.json 생성.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y-%m-%d")

# ══════════════════════════════════════════════════════════════
# 버전 메타 (profile.md와 싱크 확인용)
# ══════════════════════════════════════════════════════════════
CLASSIFY_VERSION = "v8.3"
KEYWORDS_VERSION = "2026-04-19"

# ══════════════════════════════════════════════════════════════
# 공통 상수 (v7에서 재사용)
# ══════════════════════════════════════════════════════════════

GREEN_REGIONS = {"전국", "인천"}
RED_REGIONS_EXCLUSIVE = {
    "부산", "대구", "대전", "광주", "울산", "세종",
    "강원", "충북", "충남", "전북", "전남",
    "경북", "경남", "제주",
    # v8.2: 전체 도 이름 (agency·integrated_name에 "전라남도","경상북도" 등으로 자주 등장)
    "전라남도", "전라북도", "경상남도", "경상북도",
    "충청남도", "충청북도", "강원도", "제주도", "제주특별",
}
GREEN_BIZ_CLASS = {"사업화", "정책자금", "융자ㆍ보증"}
YELLOW_BIZ_CLASS = {"멘토링ㆍ컨설팅ㆍ교육", "시설ㆍ공간ㆍ보육", "창업교육",
                    "기술개발(R&D)", "기술개발(R&amp;D)", "인력",
                    "판로ㆍ해외진출", "글로벌"}
ACCEPTABLE_BIZ_ENYY = {
    "예비창업자", "1년미만", "2년미만", "3년미만",
    "5년미만", "7년미만", "10년미만",
}
RED_INDUSTRY = [
    "반도체", "팹리스", "3D프린팅", "3D 프린팅", "3D프린터", "3D 프린터",
    "3D모델링", "3D 모델링", "시제품 제작", "시작품 제작", "시제품제작",
    "시작품제작", "후가공", "금형", "메이커", "프로토타입",
    "FAB", "3D-FAB", "MFG",
    "바이오", "제약", "신약", "의약품", "의료기기", "의료", "메디컬", "헬스케어",
    "웰니스", "디바이스",
    "농업", "농식품", "수산", "축산", "농생명", "스마트팜", "식품",
    "에너지", "방산", "로봇", "항공우주", "원자력", "조선", "화학", "철강",
    "자동차부품", "UAM", "우주", "위성",
    "관광", "게임", "e스포츠", "스포츠산업",
    "생물자원", "바이오소재", "기후테크", "환경산업", "탄소", "그린뉴딜",
    "가구", "세라믹", "패션", "전통문화", "전통시장", "전통주", "한복", "뷰티",
    "화장품", "섬유",
    "건설", "건축", "부동산",
    "해운물류", "물류", "유통", "프랜차이즈",
    "그린", "탄소중립", "ESG산업",
    "모빌리티", "자율주행", "드론",
    "메타버스", "블록체인", "NFT", "Web3", "핀테크",
    "스마트공장",
    # v8.2: 딥테크 특수 도메인 (허파랑 팀 SaaS·콘텐츠와 부합 낮음)
    "양자컴퓨팅", "양자 컴퓨팅", "Quantum", "quantum",
    "양자기술", "양자 기술", "양자암호", "양자센싱",
]
RED_QUALIFICATION = [
    "OASIS", "이민자", "외국인", "여성전용", "여성창업", "여성기업",
    "제대군인", "자립청년", "소상공인전용",
    "귀농", "귀촌", "다문화가정 전용", "장애인", "북한이탈주민", "탈북",
    "시니어", "중장년", "4050", "경력보유여성",
    "고졸전형", "특성화고", "마이스터고",
    "농업인", "어업인", "임업인",
    "사회적기업가 육성", "협동조합 전용", "마을기업 전용", "자활기업",
    # v8.2: 특수신분·귀화·학생 한정
    "특별귀화", "귀화 추천", "우수인재 특별", "해외 우수인재",
    "재학생 전용", "대학(원)생 전용", "학부생 전용",
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
    # v8.2: 자금 지원이 아닌 행사·인증·홍보 (★ green 진입 차단용)
    "설명회", "간담회", "세미나 개최", "포럼 개최", "투자설명회",
    "벤처확인", "벤처인증", "인증준비", "이노비즈 인증", "메인비즈",
    "언론 홍보", "언론홍보", "홍보 지원사업", "언론 보도", "보도자료 지원",
    "KBI", "홍보영상 제작", "광고 제작 지원",
    # v8.2: 기술임치·자문·알림 서비스 (자금 지원 아님)
    "기술임치", "기술자료 임치", "임치 계약", "임치 지원",
    "통합공고 요약", "알림신청", "알림 신청", "무상 제공", "무료로 제공",
]
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
    "서울숲", "합정", "홍대입구", "신촌",
    "서울 캠퍼스", "서울캠퍼스",
    # v8.2: 서울 전담 기관 (agency에서 자주 등장)
    "서울경제진흥원", "서울산업진흥원", "SBA", "서울시청",
    "서울특별시", "서울시 경제정책실",
]
# v8.2: 경기도 시/군 단독 — 허파랑 팀 인천 본거지와 무관
GYEONGGI_CITIES_EXCLUSIVE = [
    "수원", "성남", "고양", "용인", "부천", "안산", "안양",
    "남양주", "화성", "평택", "의정부", "시흥", "파주", "광명",
    "김포", "광주시", "군포", "오산", "하남", "이천", "안성",
    "의왕", "양주", "구리", "포천", "여주",
    "판교", "동탄", "광교",
]
SEOUL_UNIVERSITY = [
    "서울대", "연세대", "고려대", "성균관대", "한양대학교 서울",
    "이화여대", "중앙대", "경희대학교 서울", "한국외대", "건국대",
    "동국대", "홍익대학교 서울", "숭실대", "세종대", "국민대",
    "숙명여대", "상명대", "서울시립대", "서울과기대", "서경대",
    "삼육대", "한성대", "광운대", "명지대", "덕성여대",
    "서울여대", "성공회대", "총신대", "서강대", "가톨릭대",
]

# 긍정 매칭 (green 타이어 요구조건)
GREEN_KEYWORDS_TITLE_ONLY = [
    "예비창업패키지", "초기창업패키지",
    "예비창업", "초기창업",
    "모두의 창업", "모두의창업",
    "유니콘 브릿지", "유니콘브릿지",
    "K-Startup 챌린지", "K-스타트업 챌린지",
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
# 헬퍼
# ══════════════════════════════════════════════════════════════

def _title_text(item: dict) -> str:
    s = item.get("structured", {}) or {}
    return f"{item.get('title','')} {s.get('integrated_name','')} {item.get('agency','')}"


def _all_text(item: dict) -> str:
    s = item.get("structured", {}) or {}
    return (
        f"{item.get('title','')} {item.get('agency','')} "
        f"{s.get('integrated_name','')} {s.get('apply_target_desc','')}"
    )


def detect_category_hints(item: dict) -> list:
    text = _all_text(item)
    s = item.get("structured", {}) or {}
    biz_class = (s.get("biz_class") or "").strip()
    hints = []
    for cat, kws in CATEGORY_HINT_MAP.items():
        if any(kw in text for kw in kws):
            hints.append(cat)
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


# ══════════════════════════════════════════════════════════════
# 5축 점수 계산
# ══════════════════════════════════════════════════════════════

def _is_local_agency_suspect(agency: str) -> tuple[bool, str]:
    """v8.3: 지자체 산하 의심 agency 감지.

    (재)·재단법인 접두사 + ○○진흥원/○○경제진흥원/○○디자인진흥원/
    테크노파크/창업지원센터/창조경제혁신센터 패턴을 탐지.
    인천 / 창업진흥원(중기부 산하 국가기관) / 중소벤처기업진흥공단 등은 면제.

    반환: (suspect, reason)
    """
    if not agency:
        return False, ""
    # 면제: 인천·국가기관
    NATIONAL_OR_INCHEON = [
        "인천", "ICCE",
        "창업진흥원",  # 중기부 산하 국가기관 (지자체 아님)
        "중소벤처기업진흥공단", "중진공", "KOSME",
        "한국콘텐츠진흥원",  # 문체부 산하 국가기관 (지역진흥원 아님)
        "정보통신산업진흥원", "NIPA",
        "한국데이터산업진흥원", "K-Data",
    ]
    for nat in NATIONAL_OR_INCHEON:
        if nat in agency:
            return False, ""
    # 의심 패턴
    LOCAL_PATTERNS = [
        ("(재)",        "재단법인 접두사"),
        ("재단법인",     "재단법인"),
        ("진흥원",       "지역진흥원"),
        ("경제진흥원",   "지자체 경제진흥원"),
        ("산업진흥원",   "지자체 산업진흥원"),
        ("디자인진흥원", "지자체 디자인진흥원"),
        ("테크노파크",   "TP"),
        ("창조경제혁신센터", "지역혁신센터"),
        ("창업지원센터", "지자체 창업센터"),
        ("창업보육센터", "창업보육센터"),
        ("청년창업센터", "청년창업센터"),
        ("청년센터",     "지자체 청년센터"),
    ]
    for pat, label in LOCAL_PATTERNS:
        if pat in agency:
            return True, f"{label}: {agency[:30]}"
    return False, ""


def _score_region(item: dict, combined: str, struct_region: str) -> tuple[str, str]:
    """region 축 점수. (level, detail)

    v8.1 강화:
    - agency("(재)부산디자인진흥원" 등 지자체 재단) + 비수도권 지역명 → orange
    - apply_target_desc의 "○○ 소재"/"○○ 관내"/"○○ 사업장" + 비수도권 → orange
    - structured.region == "전국"이라도 agency/desc에서 지역 한정이 드러나면 덮어쓴다

    v8.3 강화:
    - _is_local_agency_suspect()로 agency 접두사·단어 패턴을 조기 감지
      (인천 / 국가기관 면제). RED_REGIONS_EXCLUSIVE 리스트 의존 없이 지역한정 포착.
    """
    s = item.get("structured", {}) or {}
    agency = item.get("agency", "") or ""
    desc = (s.get("apply_target_desc", "") or "")[:400]
    integrated = s.get("integrated_name", "") or ""

    # 🟢 green: 인천 관련 키워드 어디든 있으면 최우선
    for kw in GREEN_INCHEON:
        if kw in combined:
            return "green", f"인천 매칭 ({kw})"

    # 🟠 v8.3: agency 일반 패턴 조기 감지 (RED_REGIONS_EXCLUSIVE 리스트에 없는 신규 기관도 포착)
    suspect, reason = _is_local_agency_suspect(agency)
    if suspect:
        return "orange", f"지자체 기관 의심 ({reason})"

    # 🟠 agency/desc에서 비수도권 지역 한정 감지 (structured.region="전국" 덮어씀)
    for region_kw in RED_REGIONS_EXCLUSIVE:
        # agency에 "(재)○○진흥원", "○○테크노파크" 등
        if region_kw in agency:
            return "orange", f"기관 지역 한정 (agency: {agency[:30]})"
        # desc에 "○○ 소재", "○○ 관내", "○○에 사업장"
        patterns = [f"{region_kw} 소재", f"{region_kw}에 사업", f"{region_kw} 관내",
                    f"{region_kw} 지역", f"{region_kw}광역시", f"{region_kw}시 소재",
                    f"{region_kw}도 소재"]
        for pat in patterns:
            if pat in desc or pat in integrated:
                return "orange", f"지역 한정 desc: '{pat}'"
        # integrated_name에 지역명 포함 + 전국이 안 들어감
        if region_kw in integrated and "전국" not in integrated:
            return "orange", f"사업명에 지역 포함 ({region_kw})"

    # v8.2: 경기도 시/군 단독 (agency 또는 사업명에 포함) — struct_region="전국" 덮어씀
    for city in GYEONGGI_CITIES_EXCLUSIVE:
        if city in agency:
            return "orange", f"경기 시 기관 ({city} in agency)"
        # 사업명이나 desc에 도시명이 들어 있고, 전국 키워드 없음
        city_patterns = [f"{city}시 소재", f"{city} 소재", f"{city}시 창업",
                         f"{city}시 청년", f"{city}시 사업장", f"{city}시 관내"]
        for pat in city_patterns:
            if pat in desc or pat in integrated:
                return "orange", f"경기 시 한정 desc: '{pat}'"

    # structured.region 기반 green/orange
    if struct_region in GREEN_REGIONS:
        # structured가 전국/인천이어도 agency에서 걸렸으면 위에서 orange됐을 것
        return "green", f"지역 허용 (structured={struct_region})"

    # 🟠 서울 단독 계열
    for kw in RED_SEOUL_FACILITY:
        if kw in combined:
            return "orange", f"서울 시설/지자체 ({kw})"
    for gu in SEOUL_25_GU:
        if gu in combined:
            return "orange", f"서울 구 단독 ({gu})"
    for uni in SEOUL_UNIVERSITY:
        if uni in combined:
            return "orange", f"서울 대학 ({uni})"
    if struct_region in RED_REGIONS_EXCLUSIVE:
        return "orange", f"지역 한정 ({struct_region})"
    if "서울" in combined:
        for safe in ("오픈이노베이션", "온라인", "비대면", "화상", "전국"):
            if safe in combined:
                return "yellow", f"서울 언급 있으나 {safe} 포함"
        return "orange", "서울 단독 (인천 미포함)"
    if "경기" in combined and "인천" not in combined:
        return "orange", "경기 단독 (인천 미포함)"
    # v8.2: combined 전체에서 경기 시 단독 잡기 (agency/integrated 외에도 title 전체)
    for city in GYEONGGI_CITIES_EXCLUSIVE:
        if city in combined and "인천" not in combined and "전국" not in combined:
            return "orange", f"경기 시 단독 combined ({city})"
    return "yellow", "지역 정보 애매"


def _score_stage(item: dict, combined: str) -> tuple[str, str]:
    s = item.get("structured", {}) or {}
    enyy = (s.get("biz_enyy") or "").strip()
    # orange: 후속지원·재창업·업력 초과 등
    for kw in RED_STAGE:
        if kw in combined:
            return "orange", f"단계 불일치 ({kw})"
    # green: biz_enyy가 허용 범위
    if enyy:
        parts = {p.strip() for p in enyy.split(",") if p.strip()}
        if parts & ACCEPTABLE_BIZ_ENYY:
            matched = parts & ACCEPTABLE_BIZ_ENYY
            return "green", f"업력 허용 ({','.join(sorted(matched))})"
        else:
            return "orange", f"업력 불일치 ({enyy})"
    # enyy 비었을 때 → 키워드로 판정
    if any(kw in combined for kw in ("예비창업", "초기창업", "7년 이내", "7년이내")):
        return "green", "키워드 단계 매칭"
    # 기본 yellow (애매)
    return "yellow", "단계 정보 없음"


def _score_industry(item: dict, combined: str) -> tuple[str, str]:
    # orange: 업종 한정
    for kw in RED_INDUSTRY:
        if kw in combined:
            return "orange", f"업종 한정 ({kw})"
    s = item.get("structured", {}) or {}
    # exclude_target에 제조업 한정 시그널
    excl = (s.get("exclude_target") or "").strip()
    for kw in EXCLUDE_TARGET_MFG_SIGNALS:
        if kw in excl:
            return "orange", f"제조업 한정 exclude_target ({kw[:20]})"
    # R&D 공고: 하드웨어 리스크 있지만 업종 한정은 아님 → yellow
    biz_class = (s.get("biz_class") or "").strip()
    if "R&D" in biz_class or "R&amp;D" in biz_class or "기술개발" in biz_class:
        return "yellow", f"R&D 공고 — 하드웨어 리스크 ({biz_class})"
    return "green", "업종 제한 없음"


def _score_nature(item: dict, combined: str) -> tuple[str, str]:
    # orange: 수행기관·멘토모집·입찰·B2G 등 (애초에 지원하는 공고가 아님)
    for kw in RED_NATURE:
        if kw in combined:
            return "orange", f"성격 불일치 ({kw})"
    s = item.get("structured", {}) or {}
    biz_class = (s.get("biz_class") or "").strip()
    if biz_class in GREEN_BIZ_CLASS:
        return "green", f"직접 자금성 ({biz_class})"
    if biz_class in YELLOW_BIZ_CLASS:
        return "yellow", f"간접 지원성 ({biz_class})"
    return "yellow", f"성격 분류 애매 (biz_class='{biz_class}')"


def _score_qualification(item: dict, combined: str) -> tuple[str, str]:
    s = item.get("structured", {}) or {}
    excl = (s.get("exclude_target") or "").strip()
    # orange: 자격 한정
    for kw in RED_QUALIFICATION:
        if kw in combined:
            return "orange", f"자격 한정 ({kw})"
    # orange: exclude_target에 명시적 제외
    for kw in ("대기업", "중견기업", "공공기관 재직자", "휴·폐업", "휴폐업"):
        if kw in excl:
            return "orange", f"제외대상 명시 ({kw})"
    # yellow: exclude_target이 길면 조심
    if excl and len(excl) > 120:
        return "yellow", f"exclude_target 장문 ({len(excl)}자)"
    return "green", "자격 제한 없음"


# ══════════════════════════════════════════════════════════════
# v8.3: green 티어 감사 루틴
# ══════════════════════════════════════════════════════════════

def _audit_green_tier(item: dict) -> list:
    """v8.3: green 확정 전 최종 감사. 의심 항목 발견 시 audit_flags[] 반환.

    axis_scores 계산을 통과했어도, 다음과 같은 케이스는 실제로는 1순위 부적합:
    - agency가 (재)·진흥원·테크노파크 패턴 (_is_local_agency_suspect이 _score_region에서
      이미 잡지만, 여기서 2차 방어선)
    - integrated_conditions / exclude_target에 행사성·협소 대상 시그널
    - apply_target_desc에 특정 지역 시민·대학 재학생 등 좁은 대상

    audit_flags가 하나라도 있으면 classify()가 green → yellow로 강등한다.
    """
    s = item.get("structured", {}) or {}
    agency = item.get("agency", "") or ""
    integrated_conditions = (s.get("integrated_conditions") or s.get("integ_conditions") or "")
    exclude_target = s.get("exclude_target", "") or ""
    apply_target_desc = s.get("apply_target_desc", "") or ""
    integrated_name = s.get("integrated_name", "") or ""

    flags = []

    # (1) 지자체 기관 2차 방어선
    suspect, reason = _is_local_agency_suspect(agency)
    if suspect:
        flags.append({
            "type": "local_agency_suspect",
            "msg": f"지자체 산하 의심: {reason}",
        })

    # (2) 행사성·홍보성 시그널 (integrated_conditions / integrated_name)
    combined_audit = f"{integrated_conditions} {integrated_name}"
    EVENT_PATTERNS = [
        "설명회 개최", "간담회 개최", "포럼 개최", "세미나 개최",
        "기념식", "시상식 개최", "기자간담회",
        "성과보고회", "성과공유회",
    ]
    for pat in EVENT_PATTERNS:
        if pat in combined_audit:
            flags.append({
                "type": "event_suspect",
                "msg": f"행사성 의심: {pat}",
            })
            break

    # (3) 협소 대상 (apply_target_desc / exclude_target)
    NARROW_PATTERNS = [
        "재학 중인 대학(원)생", "재학 중인 대학생", "대학(원)생에 한함",
        "시민만", "구민만", "도민만",
        "여성만", "만 39세 이하 여성",
        "외국인등록증 소지자", "체류자격 F-", "비자 F-",
    ]
    for pat in NARROW_PATTERNS:
        if pat in apply_target_desc or pat in exclude_target:
            flags.append({
                "type": "narrow_target_suspect",
                "msg": f"대상 협소 의심: {pat}",
            })
            break

    # (4) 자금성 위장 (실제로는 인증·홍보·임치)
    DISGUISED_PATTERNS = [
        "인증 취득 지원", "인증취득 지원", "인증서 발급",
        "기술임치 계약", "임치 수수료",
        "언론 보도 지원", "PR 지원",
    ]
    for pat in DISGUISED_PATTERNS:
        if pat in combined_audit or pat in apply_target_desc:
            flags.append({
                "type": "disguised_funding",
                "msg": f"자금성 위장 의심: {pat}",
            })
            break

    return flags


# ══════════════════════════════════════════════════════════════
# 메인 분류
# ══════════════════════════════════════════════════════════════

def classify(item: dict) -> tuple[str, dict]:
    """v8: 3티어(green/yellow/orange)만 반환. red 없음.

    마감·비모집은 여전히 "expired" 반환 (update.py에서 따로 처리).
    """
    title = item.get("title", "")
    agency = item.get("agency", "")
    s = item.get("structured", {}) or {}
    all_combined = _all_text(item)
    title_only = _title_text(item)

    checks = {}
    risks = []

    # ── 선필터: 마감·비모집 ─────────────────────────────────────
    if s.get("recruiting") is False:
        return "expired", {
            "summary_reason": "모집 종료 (recruiting=N)",
            "category_hints": [], "rule_checks": {}, "risk_flags": [],
            "axis_scores": {}, "exclusion_flags": [], "tier_logic": "expired"
        }
    end = s.get("end_date") or ""
    if end and end < TODAY:
        return "expired", {
            "summary_reason": f"마감일 경과 ({end})",
            "category_hints": [], "rule_checks": {}, "risk_flags": [],
            "axis_scores": {}, "exclusion_flags": [], "tier_logic": "expired"
        }

    # ── 5축 점수 계산 ───────────────────────────────────────────
    struct_region = (s.get("region") or "").strip()
    axis_region_level, axis_region_detail = _score_region(item, all_combined, struct_region)
    axis_stage_level, axis_stage_detail = _score_stage(item, all_combined)
    axis_industry_level, axis_industry_detail = _score_industry(item, all_combined)
    axis_nature_level, axis_nature_detail = _score_nature(item, all_combined)
    axis_qual_level, axis_qual_detail = _score_qualification(item, all_combined)

    axis_scores = {
        "region":        {"level": axis_region_level,   "detail": axis_region_detail},
        "stage":         {"level": axis_stage_level,    "detail": axis_stage_detail},
        "industry":      {"level": axis_industry_level, "detail": axis_industry_detail},
        "nature":        {"level": axis_nature_level,   "detail": axis_nature_detail},
        "qualification": {"level": axis_qual_level,     "detail": axis_qual_detail},
    }
    exclusion_flags = [
        {"axis": k, "severity": "high" if v["level"] == "orange" else "low", "msg": v["detail"]}
        for k, v in axis_scores.items() if v["level"] == "orange"
    ]

    # ── 긍정 매칭(green 조건) ──────────────────────────────────
    positive_hit = None
    positive_strong = False  # title_only 또는 인천 매칭 or GREEN_BIZ_CLASS + 지역 OK
    biz_class = (s.get("biz_class") or "").strip()

    # 우선순위 1: structured 완전 매칭 (GREEN 지역 + GREEN 자금성)
    if struct_region in GREEN_REGIONS and biz_class in GREEN_BIZ_CLASS:
        positive_hit = f"structured 완전 매칭 ({struct_region}/{biz_class})"
        positive_strong = True

    # 우선순위 2: title 핵심 키워드
    if positive_hit is None:
        for kw in GREEN_KEYWORDS_TITLE_ONLY:
            if kw in title_only:
                positive_hit = f"핵심 매칭 ({kw}) — title"
                positive_strong = True
                break

    # 우선순위 3: 인천 매칭
    if positive_hit is None:
        for kw in GREEN_INCHEON:
            if kw in all_combined:
                positive_hit = f"인천 매칭 ({kw})"
                positive_strong = True
                break

    # yellow 후보
    yellow_hit = None
    if struct_region in GREEN_REGIONS and biz_class in YELLOW_BIZ_CLASS:
        yellow_hit = f"검토 매칭 ({struct_region}/{biz_class})"
    if yellow_hit is None:
        for kw in YELLOW_KEYWORDS:
            if kw in all_combined:
                yellow_hit = f"검토 매칭 ({kw})"
                break

    # orange AI 후보 (AI 리포지셔닝)
    ai_hit = None
    for kw in ORANGE_KEYWORDS:
        if kw in all_combined:
            ai_hit = f"AI 포지셔닝 가능 ({kw})"
            break

    # ── 티어 결정 ───────────────────────────────────────────────
    all_axes_green = all(v["level"] == "green" for v in axis_scores.values())
    has_orange_axis = any(v["level"] == "orange" for v in axis_scores.values())
    yellow_axes_count = sum(1 for v in axis_scores.values() if v["level"] == "yellow")

    tier = None
    tier_logic = ""
    audit_flags = []

    if positive_strong and all_axes_green:
        tier = "green"
        tier_logic = "1순위: 5축 모두 green + 강한 긍정 매칭"
    elif positive_strong and not has_orange_axis and yellow_axes_count <= 1:
        tier = "green"
        tier_logic = "1순위: 강한 긍정 매칭 + 1축만 yellow (지원 가능)"
    elif not has_orange_axis:
        # 모든 축 green/yellow — 지원 가능
        tier = "yellow"
        reason = yellow_hit or positive_hit or "중립 매칭 — 직접 지원 가능"
        tier_logic = f"2순위: 모든 축 green/yellow, {reason}"
    else:
        # 최소 1축 orange — 3순위 (아이디어·리포지셔닝 풀)
        tier = "orange"
        if ai_hit:
            tier_logic = f"3순위 (AI 리포지셔닝): {ai_hit}"
        elif positive_strong:
            tier_logic = f"3순위 (조건 충족하나 일부 축 제약): {positive_hit}"
        elif yellow_hit:
            tier_logic = f"3순위 (아이디어·우회 가능): {yellow_hit}"
        else:
            primary_excl = exclusion_flags[0] if exclusion_flags else None
            reason = primary_excl["msg"] if primary_excl else "직접 매칭 약함"
            tier_logic = f"3순위 (참고용): {reason}"

    # ── v8.3: green 확정 전 감사 — 의심되면 yellow 강등 ──────────
    if tier == "green":
        audit_flags = _audit_green_tier(item)
        if audit_flags:
            tier = "yellow"
            tier_logic = f"2순위 (감사 강등): {audit_flags[0]['msg']}"

    summary_reason = positive_hit or yellow_hit or ai_hit or tier_logic

    # ── 기존 rule_checks (backward-compat UI용) ─────────────────
    checks["recruiting"] = {"pass": True, "value": str(s.get("recruiting", "?")), "detail": "모집 중"}
    checks["deadline"] = {"pass": True, "value": end, "detail": "마감 전"}
    checks["region"] = {"pass": axis_region_level != "orange", "value": struct_region, "detail": axis_region_detail}
    checks["biz_enyy"] = {"pass": axis_stage_level != "orange", "value": s.get("biz_enyy", ""), "detail": axis_stage_detail}
    checks["exclude_target"] = {"pass": axis_qual_level != "orange", "value": (s.get("exclude_target", "") or "")[:80], "detail": axis_qual_detail}
    checks["industry"] = {"pass": axis_industry_level != "orange", "detail": axis_industry_detail}
    checks["qualification"] = {"pass": axis_qual_level != "orange", "detail": axis_qual_detail}
    checks["stage"] = {"pass": axis_stage_level != "orange", "detail": axis_stage_detail}
    checks["nature"] = {"pass": axis_nature_level != "orange", "detail": axis_nature_detail}
    checks["region_keyword"] = {"pass": axis_region_level != "orange", "detail": axis_region_detail}
    checks["positive_hit"] = {"pass": tier != "orange" or bool(positive_hit) or bool(ai_hit), "detail": summary_reason}

    # ── risk_flags ────────────────────────────────────────────
    if "R&D" in biz_class or "R&amp;D" in biz_class or "기술개발" in biz_class:
        risks.append({
            "type": "rnd_hardware_risk", "severity": "med",
            "msg": "R&D 공고 — 하드웨어/제조 시제품 중심일 가능성",
        })
    if "R&D" in title or "기술개발" in title:
        risks.append({
            "type": "title_rnd", "severity": "high",
            "msg": "제목에 R&D/기술개발 포함 — SaaS와 부합 여부 재확인",
        })
    excl = (s.get("exclude_target") or "").strip()
    if excl and len(excl) > 100:
        risks.append({
            "type": "exclude_target_long", "severity": "low",
            "msg": f"신청 제외 대상 장문 ({len(excl)}자) — 정독 필수",
        })
    apply_target = (s.get("apply_target") or "")
    if apply_target and "일반기업" not in apply_target and "1인 창조기업" not in apply_target:
        risks.append({
            "type": "apply_target_narrow", "severity": "med",
            "msg": f"신청 대상 좁음 ({apply_target[:40]})",
        })

    category_hints = detect_category_hints(item)

    return tier, {
        "summary_reason": summary_reason,
        "category_hints": category_hints,
        "rule_checks": checks,
        "risk_flags": risks,
        "axis_scores": axis_scores,
        "exclusion_flags": exclusion_flags,
        "audit_flags": audit_flags,
        "tier_logic": tier_logic,
        "classify_version": CLASSIFY_VERSION,
    }


# ══════════════════════════════════════════════════════════════
# 스크립트 실행 (crawl_results.json → recommendations.json)
# ══════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("Usage: python classify_v8.py <crawl_results.json> [existing_pool.json] > recommendations.json",
              file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        crawled = json.load(f)

    existing_pool = {"schema_version": 4, "last_updated": "", "items": []}
    if len(sys.argv) >= 3:
        try:
            with open(sys.argv[2], "r", encoding="utf-8") as f:
                existing_pool = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    existing_by_sn = {
        it.get("pbancSn", ""): it for it in existing_pool.get("items", []) if it.get("pbancSn")
    }

    stale_cutoff = (datetime.now(KST) - timedelta(days=14)).strftime("%Y-%m-%d")
    expired_titles = []

    all_candidates = crawled if isinstance(crawled, list) else crawled.get("items", [])

    final_items = []
    expired_count = 0
    stats = {"green": 0, "yellow": 0, "orange": 0, "expired": 0}

    seen_sns = set()
    for it in all_candidates:
        sn = it.get("pbancSn", "")
        if not sn or sn in seen_sns:
            continue
        seen_sns.add(sn)

        tier, ev = classify(it)
        if tier == "expired":
            expired_count += 1
            expired_titles.append(it.get("title", ""))
            continue

        stats[tier] = stats.get(tier, 0) + 1

        # merge with existing (preserve deep_summary etc)
        if sn in existing_by_sn:
            merged = dict(existing_by_sn[sn])
            merged.update({
                "pbancSn": sn,
                "title": it.get("title") or merged.get("title", ""),
                "agency": it.get("agency") or merged.get("agency", ""),
                "deadline": it.get("deadline") or merged.get("deadline", ""),
                "url": it.get("url") or merged.get("url", ""),
                "tier": tier,
                "note": ev.get("summary_reason", ""),
                "classify_evidence": ev,
                "structured": it.get("structured") or merged.get("structured", {}),
                "last_seen": TODAY,
            })
            merged.setdefault("first_seen", TODAY)
            final_items.append(merged)
        else:
            final_items.append({
                "pbancSn": sn,
                "title": it.get("title", ""),
                "agency": it.get("agency", ""),
                "deadline": it.get("deadline", ""),
                "url": it.get("url", ""),
                "tier": tier,
                "note": ev.get("summary_reason", ""),
                "classify_evidence": ev,
                "structured": it.get("structured", {}),
                "first_seen": TODAY,
                "last_seen": TODAY,
            })

    tier_order = {"green": 0, "yellow": 1, "orange": 2}
    final_items.sort(key=lambda x: (
        tier_order.get(x.get("tier"), 9),
        x.get("deadline") or "9999-99-99",
    ))

    # v8.3: keyword_counts (profile.md와 싱크 확인용)
    keyword_counts = {
        "RED_REGIONS_EXCLUSIVE": len(RED_REGIONS_EXCLUSIVE),
        "GYEONGGI_CITIES_EXCLUSIVE": len(GYEONGGI_CITIES_EXCLUSIVE),
        "RED_INDUSTRY": len(RED_INDUSTRY),
        "RED_QUALIFICATION": len(RED_QUALIFICATION),
        "RED_STAGE": len(RED_STAGE),
        "RED_NATURE": len(RED_NATURE),
        "RED_SEOUL_FACILITY": len(RED_SEOUL_FACILITY),
        "GREEN_KEYWORDS_TITLE_ONLY": len(GREEN_KEYWORDS_TITLE_ONLY),
        "GREEN_INCHEON": len(GREEN_INCHEON),
        "YELLOW_KEYWORDS": len(YELLOW_KEYWORDS),
        "ORANGE_KEYWORDS": len(ORANGE_KEYWORDS),
    }

    # v8.3: 감사 강등 통계
    audit_demoted = sum(
        1 for it in final_items
        if (it.get("classify_evidence", {}).get("audit_flags") or [])
    )

    result = {
        "schema_version": 5,  # v8 3-tier scheme
        "last_updated": TODAY,
        "items": final_items,
        "history": existing_pool.get("history", []),
        "_meta": {
            "version": CLASSIFY_VERSION,
            "keywords_version": KEYWORDS_VERSION,
            "scheme": "3-tier + audit, no red filter, all recruiting items kept",
            "source": "nidview JSON (kisedKstartupService/announcementInformation)",
            "expired_titles": expired_titles,
            "stats": {
                "green": stats["green"],
                "yellow": stats["yellow"],
                "orange": stats["orange"],
                "expired_removed": expired_count,
                "audit_demoted": audit_demoted,
                "total_pool": len(final_items),
            },
            "keyword_counts": keyword_counts,
        },
    }

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
