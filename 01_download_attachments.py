#!/usr/bin/env python3
"""kstartup-auto: recommendations.json 의 BIZINFO 공고 첨부 PDF 다운로드.

- 🟢🟡🟠 (red 제외) 공고만 처리, 이미 받은 건 스킵
- attachments/{pbancSn}/*.pdf 에 저장
- 동시 다운로드 (스레드 4)
- LLM 호출 없음 — Actions 또는 로컬에서 안전 실행

환경변수:
  KSTARTUP_REPO   리포 경로 (기본: 이 파일의 부모 디렉토리)
  PDF_LIMIT       처리 상한 (기본: 무제한)
  PDF_SOURCES     쉼표 구분 source 화이트리스트 (기본: bizinfo)
"""
from __future__ import annotations
import json, os, re, ssl, sys, time
import urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(os.environ.get("KSTARTUP_REPO", Path(__file__).resolve().parent))
REC = REPO / "recommendations.json"
ATTACH_DIR = REPO / "attachments"
INDEX = ATTACH_DIR / "_index.json"
LIMIT = int(os.environ.get("PDF_LIMIT") or 0)
SOURCES = set((os.environ.get("PDF_SOURCES") or "bizinfo").split(","))
INCLUDED_TIERS = {"green", "yellow", "orange"}

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE  # bizinfo 인증서 호환


def parse_attachments(structured: dict) -> list[tuple[str, str]]:
    """BIZINFO structured 에서 (url, name) 페어를 print 우선·일반 후순으로 반환."""
    pairs: list[tuple[str, str]] = []
    for u_key, n_key in [("printFlpthNm", "printFileNm"), ("flpthNm", "fileNm")]:
        urls = (structured.get(u_key) or "").split("@")
        names = (structured.get(n_key) or "").split("@")
        for u, n in zip(urls, names):
            u, n = u.strip(), n.strip()
            if u and u.startswith("http"):
                pairs.append((u, n))
    return pairs


def is_pdf(name: str, url: str) -> bool:
    n = name.lower()
    return n.endswith(".pdf") or "pdf" in url.lower()


SAFE = re.compile(r"[^\w\.\-가-힣()\[\]]+")


def safe_name(name: str) -> str:
    base = SAFE.sub("_", name)[:120]
    return base or "attachment.pdf"


def download_one(pbanc: str, url: str, name: str) -> tuple[str, str, int, str | None]:
    out_dir = ATTACH_DIR / pbanc
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / safe_name(name)
    if out.exists() and out.stat().st_size > 0:
        return (pbanc, name, out.stat().st_size, "skip")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (kstartup-auto)"})
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as r:
            data = r.read()
        out.write_bytes(data)
        return (pbanc, name, len(data), None)
    except Exception as e:
        return (pbanc, name, 0, str(e)[:160])


def main() -> int:
    if not REC.exists():
        print(f"[ERROR] {REC} 없음", file=sys.stderr)
        return 1
    ATTACH_DIR.mkdir(exist_ok=True)
    items = json.loads(REC.read_text(encoding="utf-8"))["items"]

    targets: list[tuple[str, str, str]] = []  # (pbancSn, url, name)
    skipped_red = skipped_other = 0
    for it in items:
        if it.get("source") not in SOURCES:
            skipped_other += 1
            continue
        if it.get("tier") not in INCLUDED_TIERS:
            skipped_red += 1
            continue
        pbanc = str(it.get("pbancSn") or it.get("id"))
        for url, name in parse_attachments(it.get("structured") or {}):
            if is_pdf(name, url):
                targets.append((pbanc, url, name))

    if LIMIT > 0:
        targets = targets[:LIMIT]
    print(f"[download_attachments] 대상 {len(targets)}건 (skip red={skipped_red}, other_source={skipped_other})")

    t0 = time.time()
    summary = {"ok": 0, "skip": 0, "fail": 0, "bytes": 0, "errors": []}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(download_one, p, u, n) for p, u, n in targets]
        for fut in as_completed(futs):
            pbanc, name, size, err = fut.result()
            if err == "skip":
                summary["skip"] += 1
            elif err is None:
                summary["ok"] += 1
                summary["bytes"] += size
            else:
                summary["fail"] += 1
                summary["errors"].append({"pbancSn": pbanc, "file": name, "error": err})

    INDEX.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_targets": len(targets),
        **summary,
        "elapsed_s": round(time.time() - t0, 1),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  ok={summary['ok']} skip={summary['skip']} fail={summary['fail']} "
          f"bytes={summary['bytes']/1024/1024:.1f}MB elapsed={time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
