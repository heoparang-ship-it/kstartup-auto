#!/usr/bin/env python3
"""kstartup-auto: attachments/{pbancSn}/*.pdf → parsed/{pbancSn}/*.md (+ *.json).

opendataloader-pdf 사용. Java 11+ 와 `pip install opendataloader-pdf` 필요.
LLM 호출 없음.

2026-05-14 v2 패치 — GitHub Actions 30분 timeout 회피:
  * pbancSn 그룹 단위 multiprocessing.Process + 그룹별 timeout (기본 120s)
  * 0바이트 / 너무 큰 PDF (>PARSE_MAX_MB) 사전 스킵 + 스텁 .md 작성
  * 전체 누적 예산 (PARSE_BUDGET_S, 기본 1500s = 25분) 초과 시 중단 → 다음 실행으로 미룸
  * 실패/타임아웃 그룹은 스텁 .md 작성하여 다음 실행에서 재시도 안 함

환경변수:
  KSTARTUP_REPO    리포 경로 (기본: 이 파일의 부모 디렉토리)
  PARSE_LIMIT      처리 상한 (기본: 무제한)
  PARSE_FORCE      1이면 기존 출력 무시하고 재파싱
  PARSE_GROUP_TIMEOUT  pbancSn 그룹 1개 당 timeout 초 (기본: 120)
  PARSE_MAX_MB     PDF 1개당 최대 크기 MB (기본: 30, 초과 시 스킵)
  PARSE_BUDGET_S   전체 step 누적 timeout 초 (기본: 1500, 25분)
"""
from __future__ import annotations
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

REPO = Path(os.environ.get("KSTARTUP_REPO", Path(__file__).resolve().parent))
ATTACH_DIR = REPO / "attachments"
PARSED_DIR = REPO / "parsed"
INDEX = PARSED_DIR / "_index.json"
LIMIT = int(os.environ.get("PARSE_LIMIT") or 0)
FORCE = os.environ.get("PARSE_FORCE") == "1"
GROUP_TIMEOUT = int(os.environ.get("PARSE_GROUP_TIMEOUT") or 120)
MAX_MB = float(os.environ.get("PARSE_MAX_MB") or 30)
BUDGET_S = int(os.environ.get("PARSE_BUDGET_S") or 1500)


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


def _worker_group(pdf_strs: list[str], out_dir_str: str, q: "mp.Queue") -> None:
    """별도 프로세스에서 opendataloader-pdf 실행. 결과를 큐로 전달."""
    try:
        import opendataloader_pdf  # type: ignore
        opendataloader_pdf.convert(
            input_path=pdf_strs,
            output_dir=out_dir_str,
            format="markdown,json",
        )
        q.put(("ok", None))
    except Exception as e:  # pragma: no cover
        q.put(("fail", str(e)[:200]))


def parse_group(pdfs: list[Path], out_dir: Path, timeout: int) -> tuple[str, str | None]:
    """pbancSn 그룹 단위로 별도 프로세스에서 파싱. timeout 초과 시 강제 종료."""
    q: "mp.Queue" = mp.Queue()
    p = mp.Process(
        target=_worker_group,
        args=([str(x) for x in pdfs], str(out_dir) + "/", q),
        daemon=False,
    )
    p.start()
    p.join(timeout=timeout)
    if p.is_alive():
        p.terminate()
        p.join(5)
        if p.is_alive():
            p.kill()
            p.join()
        return ("timeout", f"group_timeout_{timeout}s")
    try:
        status, err = q.get_nowait()
        return (status, err)
    except Exception:
        return ("fail", "no_result_from_subprocess")


def write_stub(out_md: Path, reason: str) -> None:
    """파싱 못 한 PDF에 대해 스텁 .md 작성 — 다음 실행 때 재시도 안 함."""
    out_md.parent.mkdir(exist_ok=True, parents=True)
    out_md.write_text(f"# [SKIPPED] {reason}\n", encoding="utf-8")


def main() -> int:
    try:
        import opendataloader_pdf  # noqa: F401 — 사전 import 체크
    except ImportError:
        print("[ERROR] pip install opendataloader-pdf 필요", file=sys.stderr)
        return 1

    targets = collect_targets()
    if LIMIT > 0:
        targets = targets[:LIMIT]
    print(
        f"[parse_attachments v2] 대상 {len(targets)}건 "
        f"(FORCE={FORCE} group_timeout={GROUP_TIMEOUT}s max={MAX_MB}MB budget={BUDGET_S}s)"
    )
    if not targets:
        return 0

    PARSED_DIR.mkdir(exist_ok=True)

    # 1) 사전 필터: 0바이트 / 너무 큰 PDF는 스텁 작성 후 제외
    by_pbanc: dict[str, list[Path]] = {}
    pre_skipped_large = 0
    pre_skipped_empty = 0
    for pdf, out_md in targets:
        try:
            size = pdf.stat().st_size
        except OSError:
            pre_skipped_empty += 1
            write_stub(out_md, "stat_failed")
            continue
        if size == 0:
            pre_skipped_empty += 1
            write_stub(out_md, "empty_pdf_0_bytes")
            continue
        size_mb = size / 1024 / 1024
        if size_mb > MAX_MB:
            pre_skipped_large += 1
            write_stub(out_md, f"too_large_{size_mb:.1f}MB_gt_{MAX_MB}MB")
            continue
        by_pbanc.setdefault(pdf.parent.name, []).append(pdf)

    print(
        f"  사전 스킵: empty={pre_skipped_empty} large={pre_skipped_large} "
        f"→ 실제 파싱 그룹 {len(by_pbanc)}개"
    )

    # 2) 그룹 단위 파싱 (타임아웃 + 예산)
    t0 = time.time()
    ok = fail = group_timeout = 0
    errors: list[dict] = []
    budget_exceeded = False
    remaining_groups = 0

    for gi, (pbanc, pdfs) in enumerate(by_pbanc.items()):
        elapsed = time.time() - t0
        if elapsed > BUDGET_S:
            remaining_groups = len(by_pbanc) - gi
            budget_exceeded = True
            print(
                f"  [budget exceeded] elapsed={elapsed:.0f}s "
                f"→ 남은 그룹 {remaining_groups}개 다음 실행으로 미룸"
            )
            break

        out_dir = PARSED_DIR / pbanc
        out_dir.mkdir(exist_ok=True)
        status, err = parse_group(pdfs, out_dir, GROUP_TIMEOUT)
        if status == "ok":
            ok += len(pdfs)
        elif status == "timeout":
            group_timeout += len(pdfs)
            errors.append({"pbancSn": pbanc, "error": err, "files": len(pdfs)})
            # 스텁 작성 — 재시도 방지
            for pdf in pdfs:
                stub = out_dir / (pdf.stem + ".md")
                if not stub.exists():
                    write_stub(stub, f"group_timeout_{GROUP_TIMEOUT}s")
        else:  # fail
            fail += len(pdfs)
            errors.append({"pbancSn": pbanc, "error": err, "files": len(pdfs)})
            for pdf in pdfs:
                stub = out_dir / (pdf.stem + ".md")
                if not stub.exists():
                    write_stub(stub, f"parse_failed: {err}")

    elapsed_s = round(time.time() - t0, 1)
    INDEX.write_text(
        json.dumps(
            {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "total": len(targets),
                "ok": ok,
                "fail": fail,
                "group_timeout": group_timeout,
                "pre_skipped_empty": pre_skipped_empty,
                "pre_skipped_large": pre_skipped_large,
                "budget_exceeded": budget_exceeded,
                "remaining_groups": remaining_groups,
                "group_timeout_s": GROUP_TIMEOUT,
                "max_mb": MAX_MB,
                "budget_s": BUDGET_S,
                "elapsed_s": elapsed_s,
                "errors": errors[:50],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"  ok={ok} fail={fail} group_timeout={group_timeout} "
        f"pre_skip(empty={pre_skipped_empty} large={pre_skipped_large}) "
        f"budget_exceeded={budget_exceeded} elapsed={elapsed_s}s"
    )
    # group_timeout/fail/budget이 있어도 exit 0 — 워크플로우 commit/push 단계 진행
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
