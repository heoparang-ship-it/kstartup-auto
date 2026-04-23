#!/usr/bin/env python3
"""kstartup-auto 리포의 🟢🟡 공고 중 deep_analysis/{pbancSn}.json 없는 건만
pending_deep_analysis.json에 쌓는다. GitHub Actions에서 실행.
LLM은 호출하지 않는다 (세션 fan-out 전용)."""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

def _resolve_repo() -> Path:
    # 1) 환경변수 우선 (로컬 테스트·특수 배치용)
    env = os.environ.get("KSTARTUP_REPO")
    if env:
        return Path(env).resolve()
    # 2) __file__ 기준 — 일반적으로 pipelines/ 하위에서 실행되거나 리포 루트에서 실행
    here = Path(__file__).resolve().parent
    if here.name == "pipelines":
        return here.parent
    return here


REPO = _resolve_repo()
# 실제 리포는 recommendations.json (v8 접미사 없음). 구 경로도 지원.
REC = REPO / "recommendations.json"
if not REC.exists():
    alt = REPO / "recommendations_v8.json"
    if alt.exists():
        REC = alt
ANALYSIS_DIR = REPO / "deep_analysis"
PENDING = REPO / "pending_deep_analysis.json"
KST = ZoneInfo("Asia/Seoul")


def today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def main() -> int:
    if not REC.exists():
        print(f"[ERROR] {REC} 없음", file=sys.stderr)
        return 1

    d = json.loads(REC.read_text(encoding="utf-8"))
    items = d.get("items", [])
    ANALYSIS_DIR.mkdir(exist_ok=True)
    existing = {p.stem for p in ANALYSIS_DIR.glob("*.json")}
    t = today()

    pending: list[dict] = []
    skipped = {"tier": 0, "expired": 0, "already": 0}

    for it in items:
        tier = it.get("tier")
        if tier not in ("green", "yellow"):
            skipped["tier"] += 1
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
            "skipped_non_tier": skipped["tier"],
            "skipped_expired": skipped["expired"],
            "skipped_already_analyzed": skipped["already"],
        },
    }
    PENDING.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[pending_deep_analysis] 대기: {len(pending)}건")
    print(f"  - 전체 items: {len(items)}")
    print(f"  - 🟢🟡 외 제외: {skipped['tier']}")
    print(f"  - 이미 마감: {skipped['expired']}")
    print(f"  - 이미 분석 완료: {skipped['already']}")

    if os.environ.get("ENABLE_DEEP_ANALYSIS") == "1":
        print("⚠ ENABLE_DEEP_ANALYSIS=1 감지 — Actions에서 LLM 호출은 허용되지 않음. "
              "Cowork 세션에서 처리하세요.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
