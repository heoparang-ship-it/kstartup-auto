#!/usr/bin/env python3
"""kstartup-auto: parsed/{id}/*.md + recommendations.json + deep_analysis/{id}.json
→ pending_pdf_score/{key}.json (per-key 핸드오프, 토큰 절감 v2)

v2 변경 (2026-04-27):
- 단일 pending_pdf_score.json → pending_pdf_score/{key}.json 디렉토리 (서브에이전트가 자기 파일만 읽음)
- pdf_text cap 40k → 15k (자격·예산·평가지표는 첫 페이지에 집중)
- 인덱스 파일 pending_pdf_score/_index.json (큐 요약)

기존 verdict 는 보존하고 pdf_pass_rate / roi_score / alternatives 만 추가.

환경변수:
  KSTARTUP_REPO   리포 경로
  SCORE_LIMIT     처리 상한
  SCORE_FORCE     1이면 기존 점수 무시하고 재처리
  PDF_TEXT_CAP    pdf 본문 cap (기본 15000)
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
PENDING_DIR = REPO / "pending_pdf_score"
PENDING_INDEX = PENDING_DIR / "_index.json"
TARGET_PROFILE = REPO / "target_profile.md"
LIMIT = int(os.environ.get("SCORE_LIMIT") or 0)
FORCE = os.environ.get("SCORE_FORCE") == "1"
KST = ZoneInfo("Asia/Seoul")
INCLUDED_TIERS = {"green", "yellow", "orange"}

# v2: 40k → 15k (자격·예산·평가지표는 첫 페이지 집중)
PDF_TEXT_CAP = int(os.environ.get("PDF_TEXT_CAP") or 15000)


def collect_pdf_text(item_id: str) -> tuple[str, list[str]]:
    """parsed/{id} 폴더의 .md 본문을 합쳐서 (text, file_list) 반환. 각 파일 PDF_TEXT_CAP 까지."""
    sub = PARSED_DIR / item_id
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

    PENDING_DIR.mkdir(exist_ok=True)
    target_profile = TARGET_PROFILE.read_text(encoding="utf-8") if TARGET_PROFILE.exists() else ""

    score_schema = {
        "pdf_pass_rate": "float 0~1",
        "pdf_pass_rate_confidence": "low|medium|high",
        "pdf_pass_rate_evidence": "list[{quote, source_pdf}] 최대 3, PDF 원문 인용",
        "roi_score": "float 0~1",
        "roi_breakdown": "{지원금_만원, 자기부담_만원, 자기부담_pct, 작성공수_시간, 인건비상한_만원} (모르면 null)",
        "alternatives": "list[{pbancSn, title, reason}] 최대 3 또는 []",
        "killer_blockers": "list[str] 또는 []",
        "one_liner_pdf": "이모지 1개 + 한 줄 평가 (필수)",
    }

    pending_keys: list[dict] = []
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
        text, files = collect_pdf_text(item_id)
        if not text:
            skipped["no_pdf"] += 1
            continue
        v = existing_verdict(item_id, pbanc)
        if not needs_score(v):
            skipped["already_scored"] += 1
            continue

        per_key_payload = {
            "schema_version": 2,
            "key": item_id,
            "pbancSn": pbanc,
            "id": item_id,
            "title": it.get("title"),
            "tier": it.get("tier"),
            "deadline": dl,
            "agency": it.get("agency"),
            "url": it.get("url"),
            "best_entity": it.get("best_entity"),
            "rationale_short": it.get("rationale_short"),
            "structured_excerpt": {
                k: it.get("structured", {}).get(k)
                for k in ("pblancNm", "bsnsSumryCn", "trgetNm", "reqstMthPapersCn")
            },
            "deep_analysis_existing_verdict": v,
            "pdf_files": files,
            "pdf_text": text,
            "target_profile": target_profile,
            "score_schema": score_schema,
        }
        out_path = PENDING_DIR / f"{item_id}.json"
        out_path.write_text(json.dumps(per_key_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        pending_keys.append({
            "key": item_id,
            "title": it.get("title"),
            "tier": it.get("tier"),
            "deadline": dl,
            "pdf_text_chars": len(text),
        })

    if LIMIT > 0:
        # 초과분 파일 삭제
        for entry in pending_keys[LIMIT:]:
            (PENDING_DIR / f"{entry['key']}.json").unlink(missing_ok=True)
        pending_keys = pending_keys[:LIMIT]

    PENDING_INDEX.write_text(json.dumps({
        "generated_at": datetime.now(KST).isoformat(),
        "schema_version": 2,
        "pdf_text_cap": PDF_TEXT_CAP,
        "target_count": len(pending_keys),
        "pending": pending_keys,
        "stats": {"total_items": len(items), **skipped},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # 평균/총 토큰 추정 (1 token ≈ 3 chars 한국어 기준)
    if pending_keys:
        avg = sum(p["pdf_text_chars"] for p in pending_keys) // len(pending_keys)
        total = sum(p["pdf_text_chars"] for p in pending_keys)
        print(f"[pending_pdf_score v2] 큐 {len(pending_keys)}건 → pending_pdf_score/{{key}}.json")
        print(f"  pdf_text 평균 {avg} chars, 총 {total} chars (~{total//3//1000}k 토큰 추정)")
    else:
        print(f"[pending_pdf_score v2] 큐 0건 — 새 점수화 대상 없음")
    print(f"  전체 items: {len(items)}")
    for k, v in skipped.items():
        print(f"  - {k}: {v}")
    if os.environ.get("ENABLE_PDF_SCORE") == "1":
        print("⚠ ENABLE_PDF_SCORE=1 감지 — Actions 내 LLM 호출 금지.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
