#!/usr/bin/env python3
"""남은 🟠 공고를 자동 NO-GO JSON으로 채우는 bulk 스크립트.
classify_evidence.rule_checks의 fail 항목과 structured 필드를 읽어
각 건마다 고유한 critical_gap·reasons를 가진 JSON을 생성한다. LLM 사용 안 함.

사용 시점: Cowork 세션 Sonnet 토큰 한도 소진 후, 남은 🟠 건을 빠르게 채울 때."""
from __future__ import annotations
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent
PENDING = json.loads((REPO / "pending_deep_analysis.json").read_text(encoding="utf-8"))
ANALYSIS = REPO / "deep_analysis"
ANALYSIS.mkdir(exist_ok=True)
existing = {p.stem for p in ANALYSIS.glob("*.json") if not p.name.startswith("_")}

remaining = [i for i in PENDING["pending"] if str(i["pbancSn"]) not in existing]

TODAY = "2026-04-24T17:30:00+09:00"

COMMON_ALTS = [
    {"name": "모두의 창업 로컬트랙(대구경북)", "deadline": "2026-05-15",
     "track": "와이프", "priority": "🟢", "reason": "예비창업 매칭 100%, 춘기 공백기 핵심 카드"},
    {"name": "파주 청년창업", "deadline": "2026-05-15",
     "track": "와이프", "priority": "🟢", "reason": "경기 예창 백업, 이중지원 전략 가능"},
    {"name": "2026 유니콘 브릿지(경기)", "deadline": "2026-05-15",
     "track": "본인/공동", "priority": "🟡", "reason": "sinhon.life 기창업 트랙"},
]

RULE_LABEL = {
    "recruiting": "모집 상태", "deadline": "마감일", "region": "지역",
    "biz_enyy": "업력", "exclude_target": "지원 제외 대상",
    "industry": "업종", "qualification": "자격", "stage": "창업 단계",
    "nature": "공고 성격", "region_keyword": "지역 키워드", "positive_hit": "매칭 키워드",
}


def build_nogo(it: dict) -> dict:
    title = it.get("title", "")
    ev = it.get("classify_evidence", {}) or {}
    st = it.get("structured", {}) or {}
    rc = ev.get("rule_checks", {}) or {}

    fails = []  # (label, detail)
    for k, v in rc.items():
        if not v or v.get("pass"):
            continue
        lab = RULE_LABEL.get(k, k)
        detail = v.get("detail") or v.get("value") or ""
        fails.append((lab, detail))

    # critical_gap: 실패 항목 상위 3개 요약
    if fails:
        critical = " · ".join(f"{l}: {d}" for l, d in fails[:3])
    else:
        summary = ev.get("summary_reason", "")
        critical = f"분류 근거: {summary}" if summary else "공고 성격이 허파랑/엑스컴/와이프 트랙과 직접 매칭 없음"

    # body: 공고 대상 설명
    parts = []
    if st.get("apply_target_desc"):
        parts.append(f"대상: {st['apply_target_desc']}")
    et = st.get("exclude_target", "")
    if et and "상세내용" not in et and et:
        parts.append(f"제외: {et}")
    if st.get("region"):
        parts.append(f"지역: {st['region']}")
    if st.get("biz_enyy"):
        parts.append(f"업력: {st['biz_enyy']}")
    body = " · ".join(parts)[:280] if parts else (st.get("content", title)[:240])

    reasons = [f"{l}: {d}" for l, d in fails[:4]]
    if not reasons:
        reasons = ["classify_evidence상 자격·매칭 요건 미달", "허파랑/엑스컴/와이프 트랙과 직접 매칭 없음"]

    one_liner = f"🟠 규칙 기반 NO-GO — {critical}"[:180]

    summary_reason = ev.get("summary_reason", "")

    return {
        "pbancSn": it["pbancSn"],
        "title": title,
        "analyzed_at": TODAY,
        "analyzer": "rule-based@cowork",
        "schema_version": 1,
        "target_profile": "sinhon.life + 엑스컴 + 와이프 트랙",
        "verdict": {
            "decision": "NO-GO",
            "confidence": "medium",
            "expected_pass_rate": 0.05,
            "time_cost_hours": "40-60",
            "one_liner": one_liner,
        },
        "sections": {
            "nature": {
                "title": "이 공고의 정체",
                "type": f"tier {it.get('tier','orange')} (자동 분류)",
                "body": body,
                "benefits": [],
                "watchout": "",
            },
            "fit": {
                "title": "팀 적합도 매칭",
                "direct_match": [],
                "tech_adjacent": [],
                "mismatch_note": f"classify_evidence 요약: {summary_reason}" if summary_reason else "",
                "critical_gap": critical[:220],
            },
            "roi": {
                "title": "ROI 계산",
                "time_cost": {
                    "breakdown": [
                        {"stage": "자격 확인", "hours": "5"},
                        {"stage": "서류 작성", "hours": "30"},
                        {"stage": "발표·인터뷰", "hours": "10"},
                    ],
                    "total": "45h",
                },
                "probability": {
                    "doc_pass": 0.15,
                    "final_given_doc_pass": 0.30,
                    "final": 0.05,
                    "basis": "🟠 classify — 도메인·자격 자동 불일치 판정 기반 보수 추정",
                },
                "expected_value_krw": 0,
                "expected_value_label": "자격·도메인 매칭 미달로 실질 기댓값 거의 0원",
            },
            "decision": {
                "title": "GO/NO-GO",
                "verdict": "NO-GO",
                "reasons": reasons,
                "exception_go_conditions": [
                    "공고문 원문 재확인 후 숨은 매칭 포인트 발견 시 재검토",
                    "춘기 공백기 5/15 마감 3건 모두 마감 후 차선책으로 검토",
                ],
            },
            "alternatives": {
                "title": "대안 (같은 기간 열려 있는 공고)",
                "items": COMMON_ALTS,
            },
        },
        "_meta": {
            "cycle_phase": "spring_gap",
            "generated_from": {
                "recommendations_snapshot": "2026-04-24",
                "profile_snapshot": "target_profile.md",
                "generation_mode": "rule_based_bulk_nogo",
            },
        },
    }


def main() -> int:
    created = 0
    for it in remaining:
        out = ANALYSIS / f"{it['pbancSn']}.json"
        if out.exists():
            continue
        data = build_nogo(it)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        created += 1
    print(f"[bulk_nogo_fill] 생성: {created}건 (기존 유지: {len(remaining) - created}건)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
