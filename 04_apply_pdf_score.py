#!/usr/bin/env python3
"""kstartup-auto: 세션이 만든 점수 결과를 deep_analysis/{pbancSn}.json verdict 에 머지.

입력: scored_pdf/{pbancSn}.json — 세션이 fan-out으로 만든 점수 파일
출력: deep_analysis/{pbancSn}.json 의 verdict 에 pdf_* 필드 추가, analyzer 별도 기록.

기존 필드(decision, expected_pass_rate, ...)는 절대 덮어쓰지 않음.

환경변수:
  KSTARTUP_REPO   리포 경로
  APPLY_LIMIT     처리 상한
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(os.environ.get("KSTARTUP_REPO", Path(__file__).resolve().parent))
ANALYSIS_DIR = REPO / "deep_analysis"
SCORED_DIR = REPO / "scored_pdf"
INDEX = SCORED_DIR / "_apply_index.json"
LIMIT = int(os.environ.get("APPLY_LIMIT") or 0)
KST = ZoneInfo("Asia/Seoul")

PDF_KEYS = (
    "pdf_pass_rate", "pdf_pass_rate_confidence", "pdf_pass_rate_evidence",
    "roi_score", "roi_breakdown", "alternatives", "killer_blockers", "one_liner_pdf",
)


def revise_tier(verdict: dict) -> tuple[str | None, str]:
    """pdf_pass_rate 기반 tier 재분류.
    임계: ≥0.5 green, ≥0.2 yellow, ≥0.1 orange, <0.1 red.
    killer_blockers 있으면 한 단계 강등 (단 green 은 yellow까지만).
    반환: (tier_revised, reason)
    """
    p = verdict.get("pdf_pass_rate")
    if not isinstance(p, (int, float)):
        return None, "no_pdf_score"
    if p >= 0.5:
        base = "green"
    elif p >= 0.2:
        base = "yellow"
    elif p >= 0.1:
        base = "orange"
    else:
        base = "red"
    blockers = verdict.get("killer_blockers") or []
    if blockers and base != "red":
        downgrade = {"green": "yellow", "yellow": "orange", "orange": "red"}
        revised = downgrade.get(base, base)
        return revised, f"base={base}, blockers={len(blockers)} → 한 단계 강등"
    return base, f"base={base}"


def main() -> int:
    if not SCORED_DIR.exists():
        print(f"[ERROR] {SCORED_DIR} 없음 — 세션이 점수 파일을 먼저 만들어야 함", file=sys.stderr)
        return 1
    ANALYSIS_DIR.mkdir(exist_ok=True)
    files = sorted([p for p in SCORED_DIR.glob("*.json") if not p.name.startswith("_")])
    if LIMIT > 0:
        files = files[:LIMIT]
    print(f"[apply_pdf_score] 적용 대상 {len(files)}건")

    ok = fail = skip = 0
    log: list[dict] = []
    for f in files:
        key = f.stem  # bizinfo_PBLN_xxx (id) 또는 165441 (옛 pbancSn)
        try:
            scored = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            fail += 1
            log.append({"key": key, "error": f"parse: {e}"})
            continue

        target = ANALYSIS_DIR / f"{key}.json"
        if target.exists():
            d = json.loads(target.read_text(encoding="utf-8"))
        else:
            d = {
                "id": key,
                "pbancSn": scored.get("pbancSn"),
                "title": scored.get("title", ""),
                "schema_version": 1,
                "verdict": {},
            }

        v = d.setdefault("verdict", {})
        before = {k: v.get(k) for k in PDF_KEYS}
        for k in PDF_KEYS:
            if k in scored:
                v[k] = scored[k]
        if before == {k: v.get(k) for k in PDF_KEYS}:
            skip += 1
            continue

        # tier 재분류 (PDF 점수 기반) — 기존 tier 는 보존, verdict.tier_revised 로 별도 추가
        tier_rev, reason = revise_tier(v)
        if tier_rev:
            v["tier_revised"] = tier_rev
            v["tier_revised_reason"] = reason

        d["pdf_analyzed_at"] = datetime.now(KST).isoformat()
        d["pdf_analyzer"] = scored.get("_analyzer") or "sonnet-pdf@cowork"

        target.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        ok += 1

    INDEX.write_text(json.dumps({
        "applied_at": datetime.now(KST).isoformat(),
        "ok": ok, "skip": skip, "fail": fail,
        "log": log,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ok={ok} skip={skip} fail={fail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
