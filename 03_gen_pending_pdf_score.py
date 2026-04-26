#!/usr/bin/env python3
"""kstartup-auto: parsed/{pbancSn}/*.md + recommendations.json + deep_analysis/{pbancSn}.json
→ pending_pdf_score.json (Cowork 세션 fan-out 핸드오프).

기존 verdict 는 보존하고 pdf_pass_rate / roi_score / alternatives 만 추가하는 게 목표.
이미 점수가 있는 건(verdict 에 pdf_pass_rate 가 있고 PDF 변경 없음)은 스킵.

환경변수:
  KSTARTUP_REPO   리포 경로
  SCORE_LIMIT     처리 상한
  SCORE_FORCE     1이면 기존 점수 무시하고 재처리
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(os.environ.get("KSTARTUP_REPO", Path(__file__).resolve().parent))
REC = REPO / "recommendations.json"
PARSED_DIR = REPO / "parsed"
ANALYSIS_DIR = REPO / "deep_analysis"
PENDING = REPO / "pending_pdf_score.json"
TARGET_PROFILE = REPO / "target_profile.md"
LIMIT = int(os.environ.get("SCORE_LIMIT") or 0)
FORCE = os.environ.get("SCORE_FORCE") == "1"
KST = ZoneInfo("Asia/Seoul")
INCLUDED_TIERS = {"green", "yellow", "orange"}

# 점수화 시 LLM 컨텍스트 폭발 방지 — md 한 파일당 본문 길이 상한 (문자)
PDF_TEXT_CAP = 40000  # ≈ 12k tokens 상당


def collect_pdf_text(pbanc: str) -> tuple[str, list[str]]:
    """pbancSn 폴더의 .md 본문을 합쳐서 (text, file_list) 반환."""
    sub = PARSED_DIR / pbanc
    if not sub.exists():
        return "", []
    files: list[str] = []
    chunks: list[str] = []
    for md in sorted(sub.glob("*.md")):
        files.append(md.name)
        body = md.read_text(encoding="utf-8", errors="ignore")
        if len(body) > PDF_TEXT_CAP:
            body = body[:PDF_TEXT_CAP] + f"\n\n[…{len(body)-PDF_TEXT_CAP} chars truncated…]"
        chunks.append(f"### 첨부: {md.name}\n\n{body}")
    return "\n\n---\n\n".join(chunks), files


def existing_verdict(item_id: str, pbanc: str | None) -> dict:
    """deep_analysis/{id}.json 우선, 없으면 옛 deep_analysis/{pbancSn}.json fallback."""
    for stem in (item_id, pbanc):
        if not stem:
            continue
        p = ANALYSIS_DIR / f"{stem}.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8")).get("verdict", {}) or {}
            except Exception:
                pass
    return {}


def needs_score(verdict: dict) -> bool:
    if FORCE:
        return True
    return "pdf_pass_rate" not in verdict


def main() -> int:
    if not REC.exists():
        print(f"[ERROR] {REC} 없음", file=sys.stderr)
        return 1
    items = json.loads(REC.read_text(encoding="utf-8"))["items"]
    today = datetime.now(KST).strftime("%Y-%m-%d")

    pending: list[dict] = []
    skipped = {"red": 0, "expired": 0, "no_pdf": 0, "already_scored": 0}

    for it in items:
        if it.get("tier") not in INCLUDED_TIERS:
            skipped["red"] += 1
            continue
        dl = it.get("deadline") or ""
        if dl and dl < today:
            skipped["expired"] += 1
            continue
        item_id = str(it.get("id") or it.get("pbancSn") or "")
        pbanc = it.get("pbancSn")
        if not item_id:
            continue
        text, files = collect_pdf_text(item_id)  # parsed/ 폴더는 id 기준
        if not text:
            skipped["no_pdf"] += 1
            continue
        v = existing_verdict(item_id, pbanc)
        if not needs_score(v):
            skipped["already_scored"] += 1
            continue
        pending.append({
            "key": item_id,            # primary key — scored_pdf/{key}.json 파일명, deep_analysis/{key}.json 매칭
            "pbancSn": pbanc,           # 정보용 (None 가능)
            "id": item_id,
            "title": it.get("title"),
            "tier": it.get("tier"),
            "deadline": dl,
            "agency": it.get("agency"),
            "url": it.get("url"),
            "best_entity": it.get("best_entity"),
            "domain": it.get("domain"),
            "entities": it.get("entities"),
            "rationale_short": it.get("rationale_short"),
            "structured_excerpt": {
                k: it.get("structured", {}).get(k)
                for k in ("pblancNm", "bsnsSumryCn", "trgetNm", "reqstMthPapersCn",
                          "pldirSportRealmLclasCodeNm", "creatPnttm", "reqstBeginEndDe")
            },
            "deep_analysis_existing_verdict": v,
            "pdf_files": files,
            "pdf_text": text,
        })

    if LIMIT > 0:
        pending = pending[:LIMIT]

    target_profile = TARGET_PROFILE.read_text(encoding="utf-8") if TARGET_PROFILE.exists() else ""
    payload = {
        "generated_at": datetime.now(KST).isoformat(),
        "schema_version": 1,
        "target_profile": target_profile,
        "score_schema": {
            "pdf_pass_rate": "float 0~1, 자격요건·평가지표 매칭 기반 합격가능성",
            "pdf_pass_rate_evidence": "list[{quote, source_pdf}], 합격가능성 근거 인용 1~3개",
            "pdf_pass_rate_confidence": "low|medium|high",
            "roi_score": "float 0~1, (지원금 vs 자기부담·작성공수) 비율 정규화",
            "roi_breakdown": "{지원금_만원: int|null, 자기부담_만원: int|null, 자기부담_pct: float|null, 작성공수_시간: int|null, 인건비상한_만원: int|null}",
            "alternatives": "list[{pbancSn, title, reason}] top 3 — 같은 사용자가 노릴 만한 다른 공고",
            "killer_blockers": "list[str] — 이 공고를 NO-GO로 만들 결정적 사유",
            "one_liner_pdf": "str — PDF 기반 최종 한 줄 평",
        },
        "pending": pending,
        "target_count": len(pending),
        "stats": {"total_items": len(items), **skipped},
    }
    PENDING.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[pending_pdf_score] 대기: {len(pending)}건")
    print(f"  - 전체 items: {len(items)}")
    for k, v in skipped.items():
        print(f"  - {k}: {v}")
    if os.environ.get("ENABLE_PDF_SCORE") == "1":
        print("⚠ ENABLE_PDF_SCORE=1 감지 — Actions 내 LLM 호출은 금지. Cowork 세션에서 처리.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
