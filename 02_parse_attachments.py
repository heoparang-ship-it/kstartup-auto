#!/usr/bin/env python3
"""kstartup-auto: attachments/{pbancSn}/*.pdf → parsed/{pbancSn}/*.md (+ *.json).

opendataloader-pdf 사용. Java 11+ 와 `pip install opendataloader-pdf` 필요.
LLM 호출 없음.

환경변수:
  KSTARTUP_REPO   리포 경로 (기본: 이 파일의 부모 디렉토리)
  PARSE_LIMIT     처리 상한 (기본: 무제한)
  PARSE_FORCE     1이면 기존 출력 무시하고 재파싱
"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path

REPO = Path(os.environ.get("KSTARTUP_REPO", Path(__file__).resolve().parent))
ATTACH_DIR = REPO / "attachments"
PARSED_DIR = REPO / "parsed"
INDEX = PARSED_DIR / "_index.json"
LIMIT = int(os.environ.get("PARSE_LIMIT") or 0)
FORCE = os.environ.get("PARSE_FORCE") == "1"


def collect_targets() -> list[tuple[Path, Path]]:
    targets: list[tuple[Path, Path]] = []
    if not ATTACH_DIR.exists():
        return targets
    for sub in sorted(ATTACH_DIR.iterdir()):
        if not sub.is_dir() or sub.name.startswith("_"):
            continue
        for pdf in sorted(sub.glob("*.pdf")):
            out_md = PARSED_DIR / sub.name / (pdf.stem + ".md")
            if out_md.exists() and not FORCE:
                continue
            targets.append((pdf, out_md))
    return targets


def main() -> int:
    try:
        import opendataloader_pdf  # type: ignore
    except ImportError:
        print("[ERROR] pip install opendataloader-pdf 필요", file=sys.stderr)
        return 1

    targets = collect_targets()
    if LIMIT > 0:
        targets = targets[:LIMIT]
    print(f"[parse_attachments] 대상 {len(targets)}건 (FORCE={FORCE})")
    if not targets:
        return 0

    PARSED_DIR.mkdir(exist_ok=True)

    # opendataloader-pdf는 한 번 호출에 여러 파일 일괄 처리하는 게 효율적 (JVM 1회 부팅).
    # 그러나 출력 디렉토리가 평면이라 pbancSn 별로 묶어서 호출.
    by_pbanc: dict[str, list[Path]] = {}
    for pdf, _ in targets:
        by_pbanc.setdefault(pdf.parent.name, []).append(pdf)

    t0 = time.time()
    ok = fail = 0
    errors: list[dict] = []
    for pbanc, pdfs in by_pbanc.items():
        out_dir = PARSED_DIR / pbanc
        out_dir.mkdir(exist_ok=True)
        try:
            opendataloader_pdf.convert(
                input_path=[str(p) for p in pdfs],
                output_dir=str(out_dir) + "/",
                format="markdown,json",
            )
            ok += len(pdfs)
        except Exception as e:
            fail += len(pdfs)
            errors.append({"pbancSn": pbanc, "error": str(e)[:200]})

    INDEX.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total": len(targets),
        "ok": ok,
        "fail": fail,
        "elapsed_s": round(time.time() - t0, 1),
        "errors": errors,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  ok={ok} fail={fail} elapsed={time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
