#!/usr/bin/env python3
"""
K-Startup 공고 자동 분류기 (profile.md 규칙 기반)
- LLM 토큰 소모 없이 규칙 기반 즉시 분류
- tier: green / yellow / orange / red
"""

from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y-%m-%d")

# ── 🔴 즉시 제외 ─────────────────────────────────────────────
RED_INDUSTRY = [
    "반도체", "팹리스", "바이오", "농업", "에너지", "방산", "로봇", "항공우주",
    "관광", "게임", "가구", "세라믹", "해운물류", "패션", "의료기기", "의료",
    "제조", "식품", "농식품", "수산", "축산", "원자력", "조선", "섬유",
    "화학", "철강", "자동차부품", "전통문화",
]
RED_QUALIFICATION = [
    "OASIS", "이민자", "외국인", "여성전용", "여성창업", "제대군인", "자립청년",
    "소상공인", "소상공인전용", "귀농", "귀촌", "다문화",
]
RED_STAGE = [
    "후속지원", "Series A", "Series B", "IPO", "수출실적", "업력 3년 초과",
    "업력 5년", "업력 7년", "재도전", "재창업",
]
RED_NATURE = [
    "수행기관", "수행사", "운영기관 모집", "위탁운영", "B2G", "공공시장 진출",
    "공공조달", "조달시장", "파트너사 모집",
]
RED_REGION_EXCLUSIVE = [
    "부산", "대구", "대전", "광주", "울산", "강원", "충북", "충남", "전북", "전남",
    "경북", "경남", "제주", "세종", "비수도권",
]
RED_SEOUL_FACILITY = [
    "서울창업허브 입주", "서울 입주", "성수 입주", "마포 입주", "강남 입주",
    "도봉", "구로", "금천", "동대문", "성남", "파주", "안산", "고양", "과천",
]

# ── 🟢 강력 매칭 ─────────────────────────────────────────────
GREEN_KEYWORDS = [
    "예비창업패키지", "초기창업패키지", "예비창업", "초기창업",
    "모두의 창업", "모두의창업", "유니콘 브릿지", "유니콘브릿지",
    "사업화", "범용",
]
GREEN_INCHEON = [
    "인천창조경제혁신센터", "인천테크노파크", "인천스타트업파크",
    "남동구", "인천 청년", "인천창업",
]

# ── 🟡 검토 ──────────────────────────────────────────────────
YELLOW_KEYWORDS = [
    "액셀러레이팅", "액셀러레이터", "청년창업", "IP디딤돌", "IP 디딤돌",
    "사회적기업", "사회적경제", "콘텐츠", "크리에이터", "1인미디어",
    "IT", "디지털", "설명회", "교육", "세미나", "네트워킹",
    "오픈이노베이션", "경진대회", "해커톤", "데모데이", "피칭", "IR",
    "팁스", "TIPS", "프리팁스", "Pre-TIPS",
    "글로벌", "투자연계", "GMEP", "보육",
]

# ── 🟠 AI 포지셔닝 ───────────────────────────────────────────
ORANGE_KEYWORDS = [
    "AX", "LLM", "AI대전환", "AI 대전환", "AI바우처", "AI 바우처",
    "AI 실증", "인공지능", "클라우드", "데이터", "딥테크",
]


def _check_region(combined: str) -> str | None:
    """지역 🔴 판정. 제외 사유 반환, 통과 시 None."""
    if "전국" in combined or "인천" in combined or "수도권" in combined:
        return None
    if "서울" in combined and "경기" in combined and "인천" in combined:
        return None

    for kw in RED_SEOUL_FACILITY:
        if kw in combined:
            return f"서울 시설/지자체 단독 ({kw})"

    for region in RED_REGION_EXCLUSIVE:
        if region in combined:
            return f"지역 한정 ({region})"

    if "서울" in combined and "인천" not in combined and "전국" not in combined:
        if any(k in combined for k in ["오픈이노베이션", "프로그램", "온라인", "비대면"]):
            return None
        return "서울 단독 (인천 미포함)"

    if "경기" in combined and "인천" not in combined and "전국" not in combined:
        return "경기 단독 (인천 미포함)"

    return None


def classify(item: dict) -> tuple[str, str]:
    """
    공고 1건 분류. Returns (tier, reason).
    tier: "green" | "yellow" | "orange" | "red"
    """
    title = item.get("title", "")
    agency = item.get("agency", "")
    combined = title + " " + agency

    # ── 1. 🔴 즉시 제외 ──
    for group, label in [
        (RED_INDUSTRY, "업종 한정"),
        (RED_QUALIFICATION, "자격 한정"),
        (RED_STAGE, "단계 불일치"),
        (RED_NATURE, "성격 불일치"),
    ]:
        for kw in group:
            if kw in combined:
                return "red", f"{label} ({kw})"

    region_reason = _check_region(combined)
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

    # ── 4. 🟡 검토 ──
    for kw in YELLOW_KEYWORDS:
        if kw in combined:
            return "yellow", f"검토 매칭 ({kw})"

    # ── 5. 🟠 AI 포지셔닝 ──
    for kw in ORANGE_KEYWORDS:
        if kw in combined:
            return "orange", f"AI 포지셔닝 ({kw})"

    # ── 6. 미분류 → red 제외 (키워드에 안 걸리면 관련 없을 확률 높음) ──
    return "red", "키워드 미매칭"
