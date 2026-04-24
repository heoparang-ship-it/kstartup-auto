#!/usr/bin/env python3
"""kstartup-auto 리포의 🟢🟡🟠 공고(red만 제외) 중 deep_analysis/{pbancSn}.json 없는
건만 pending_deep_analysis.json에 쌓고, deep_analysis/_index.json 을 갱신한다.
LLM은 호출하지 않는다 (세션 fan-out 전용).

v2 (2026-04-24): 🟠 포함으로 확장, _index.json 생성 추가. GO/NO-GO 필터 UI 지원."""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def _resolve_repo() -> Path:
    env = os.environ.get("KSTARTUP_REPO")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve().parent
    if here.name == "pipelines":
        return here.parent
    return here


REPO = _resolve_repo()
REC = REPO / "recommendations.json"
if not REC.exists():
    alt = REPO / "recommendations_v8.json"
    if alt.exists():
        REC = alt
ANALYSIS_DIR = REPO / "deep_analysis"
PENDING = REPO / "pending_deep_analysis.json"
VERDICT_INDEX = ANALYSIS_DIR / "_index.json"
KST = ZoneInfo("Asia/Seoul")

# 🟢 🟡 🟠 전부 분석 대상. 🔴(red)만 스킵.
INCLUDED_TIERS = {"green", "yellow", "orange"}


def today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def build_verdict_index() -> dict:
    """deep_analysis/*.json 스캔해 verdict 요약 인덱스 생성. _로 시작하는 파일 제외."""
    ANALYSIS_DIR.mkdir(exist_ok=True)
    idx: dict[str, dict] = {}
    for p in ANALYSIS_DIR.glob("*.json"):
        if p.name.startswith("_"):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            v = d.get("verdict", {}) or {}
            idx[p.stem] = {
                "decision": v.get("decision"),
                "confidence": v.get("confidence"),
                "expected_pass_rate": v.get("expected_pass_rate"),
                "one_liner": v.get("one_liner"),
                "analyzed_at": d.get("analyzed_at"),
            }
        except Exception:
            continue
    return idx


def main() -> int:
    if not REC.exists():
        print(f"[ERROR] {REC} 없음", file=sys.stderr)
        return 1

    d = json.loads(REC.read_text(encoding="utf-8"))
    items = d.get("items", [])
    ANALYSIS_DIR.mkdir(exist_ok=True)
    existing = {p.stem for p in ANALYSIS_DIR.glob("*.json") if not p.name.startswith("_")}
    t = today()

    pending: list[dict] = []
    skipped = {"red": 0, "expired": 0, "already": 0}

    for it in items:
        tier = it.get("tier")
        if tier not in INCLUDED_TIERS:
            skipped["red"] += 1
            continue
        dl = it.get("deadline") or ""
        if dl and dl < t:
            skipped["expired"] += 1
            continue
        pbanc = str(it.get("pbancSn"))
        if pbanc in existing:
            skipped["already"] += 1
            continue
        pending.append({
            "pbancSn": it.get("pbancSn"),
            "title": it.get("title"),
            "tier": tier,
            "deadline": dl,
            "agency": it.get("agency"),
            "url": it.get("url"),
            "structured": it.get("structured", {}),
            "classify_evidence": it.get("classify_evidence", {}),
            "deep_summary": it.get("deep_summary", "") or "",
        })

    payload = {
        "generated_at": datetime.now(KST).isoformat(),
        "target_profile_ref": "target_profile.md",
        "pending": pending,
        "target_count": len(pending),
        "stats": {
            "total_items": len(items),
            "skipped_red": skipped["red"],
            "skipped_expired": skipped["expired"],
            "skipped_already_analyzed": skipped["already"],
        },
    }
    PENDING.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    idx = build_verdict_index()
    VERDICT_INDEX.write_text(json.dumps({
        "generated_at": datetime.now(KST).isoformat(),
        "total": len(idx),
        "verdicts": idx,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[pending_deep_analysis] 대기: {len(pending)}건")
    print(f"  - 전체 items: {len(items)}")
    print(f"  - 🔴 제외: {skipped['red']}")
    print(f"  - 이미 마감: {skipped['expired']}")
    print(f"  - 이미 분석 완료: {skipped['already']}")
    print(f"[verdict_index] 등록: {len(idx)}건")

    if os.environ.get("ENABLE_DEEP_ANALYSIS") == "1":
        print("⚠ ENABLE_DEEP_ANALYSIS=1 감지 — Actions에서 LLM 호출은 허용되지 않음. "
              "Cowork 세션에서 처리하세요.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
