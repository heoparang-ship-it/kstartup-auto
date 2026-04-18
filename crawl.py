#!/usr/bin/env python3
"""
K-Startup 공고 크롤러 v6 — nidview 공식 JSON 엔드포인트 사용
────────────────────────────────────────────────────────────
v5의 pbancSn 시퀀셜 프로빙(~10,000회) 을 폐기하고, K-Startup 사이트 내부가
사용하는 JSON 엔드포인트를 직접 호출한다(~57회).

실측 결과 (2026-04-18):
- endpoint: https://nidview.k-startup.go.kr/view/public/call/
             kisedKstartupService/announcementInformation
- serviceKey 불필요 (공개 proxy)
- perPage 최대 500 이상 허용 (보수적으로 500 사용)
- 서버사이드 필터는 무시됨 → 로컬 `is_active()` 로 필터링
- 정렬: pbanc_sn 내림차순 (최신 먼저)

응답 필드 (주요):
  pbanc_sn, biz_pbanc_nm, intg_pbanc_biz_nm, intg_pbanc_yn,
  pbanc_ctnt, pbanc_ntrp_nm, sprv_inst,
  supt_biz_clsfc, supt_regin,
  biz_enyy, biz_trgt_age,
  aply_trgt, aply_trgt_ctnt, aply_excl_trgt_ctnt,
  rcrt_prgs_yn (모집진행여부 Y/N),
  pbanc_rcpt_bgng_dt, pbanc_rcpt_end_dt (YYYYMMDD),
  detl_pg_url, biz_gdnc_url, prfn_matr,
  aply_mthd_*_rcpt_istc, prch_cnpl_no

update.py 호환:
- 모듈 레벨 ``crawl(known_sns)`` 함수를 제공 (v5 API 유지)
- 반환 항목은 ``pbancSn``, ``title``, ``agency``, ``deadline``, ``url``,
  ``first_seen``, ``last_seen`` + ``structured`` (v6 신규)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y-%m-%d")
TODAY_YMD = datetime.now(KST).strftime("%Y%m%d")

DEFAULT_API_URL = os.environ.get(
    "K_STARTUP_API_URL",
    "https://nidview.k-startup.go.kr/view/public/call/kisedKstartupService/announcementInformation",
)
PER_PAGE = int(os.environ.get("K_STARTUP_PER_PAGE", "500"))
MAX_PAGES = int(os.environ.get("K_STARTUP_MAX_PAGES", "100"))
CURL_TIMEOUT = 30
RETRY = 3
RETRY_SLEEP = 2

DETAIL_URL_TMPL = (
    "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn={sn}"
)


def fetch_page(page: int, per_page: int = PER_PAGE) -> dict | None:
    """한 페이지 JSON 조회. 실패 시 None."""
    url = f"{DEFAULT_API_URL}?page={page}&perPage={per_page}"
    for attempt in range(RETRY):
        try:
            r = subprocess.run(
                [
                    "curl", "-s", "--max-time", str(CURL_TIMEOUT),
                    "-H", "User-Agent: Mozilla/5.0 (compatible; SinhonLifeBot/6.0)",
                    "-H", "Accept: application/json",
                    url,
                ],
                capture_output=True, text=True, timeout=CURL_TIMEOUT + 5,
            )
            body = r.stdout
            if not body:
                raise ValueError("empty body")
            data = json.loads(body)
            if "data" not in data:
                raise ValueError(f"missing 'data' key (keys={list(data.keys())})")
            return data
        except Exception as e:
            if attempt < RETRY - 1:
                print(f"  ⚠ page={page} 재시도 {attempt+1}/{RETRY}: {e}",
                      file=sys.stderr)
                time.sleep(RETRY_SLEEP * (attempt + 1))
            else:
                print(f"  ✗ page={page} 최종 실패: {e}", file=sys.stderr)
    return None


def normalize_item(raw: dict) -> dict:
    """API 응답 한 건을 내부 표준 스키마로 변환."""
    sn = str(raw.get("pbanc_sn", "")).strip()
    title = (raw.get("biz_pbanc_nm") or raw.get("intg_pbanc_biz_nm") or "").strip()
    end_dt_raw = str(raw.get("pbanc_rcpt_end_dt", "")).strip()
    deadline = ""
    if len(end_dt_raw) == 8 and end_dt_raw.isdigit():
        deadline = f"{end_dt_raw[:4]}-{end_dt_raw[4:6]}-{end_dt_raw[6:8]}"
    start_dt_raw = str(raw.get("pbanc_rcpt_bgng_dt", "")).strip()
    start_date = ""
    if len(start_dt_raw) == 8 and start_dt_raw.isdigit():
        start_date = f"{start_dt_raw[:4]}-{start_dt_raw[4:6]}-{start_dt_raw[6:8]}"

    detl_url = raw.get("detl_pg_url") or DETAIL_URL_TMPL.format(sn=sn)

    return {
        # v5 호환 필드
        "pbancSn": sn,
        "title": title,
        "agency": (raw.get("pbanc_ntrp_nm") or "").strip(),
        "deadline": deadline,
        "url": detl_url,
        "first_seen": TODAY,
        "last_seen": TODAY,
        # v6 신규 구조화 필드
        "structured": {
            "pbanc_sn_int": int(sn) if sn.isdigit() else None,
            "integrated": (raw.get("intg_pbanc_yn") == "Y"),
            "recruiting": (raw.get("rcrt_prgs_yn") == "Y"),
            "start_date": start_date,
            "end_date": deadline,
            "agency_type": (raw.get("sprv_inst") or "").strip(),
            "biz_class": (raw.get("supt_biz_clsfc") or "").strip(),
            "region": (raw.get("supt_regin") or "").strip(),
            "biz_enyy": (raw.get("biz_enyy") or "").strip(),
            "age_range": (raw.get("biz_trgt_age") or "").strip(),
            "apply_target": (raw.get("aply_trgt") or "").strip(),
            "apply_target_desc": (raw.get("aply_trgt_ctnt") or "").strip(),
            "exclude_target": (raw.get("aply_excl_trgt_ctnt") or "").strip(),
            "preferential": (raw.get("prfn_matr") or "").strip(),
            "content": (raw.get("pbanc_ctnt") or "").strip(),
            "integrated_name": (raw.get("intg_pbanc_biz_nm") or "").strip(),
            "apply_online": (raw.get("aply_mthd_onli_rcpt_istc") or "").strip(),
            "apply_guide": (raw.get("biz_gdnc_url") or "").strip(),
        },
    }


def is_active(item: dict) -> bool:
    """모집 중인 공고인지. rcrt_prgs_yn=Y 이고 today ≤ end_date."""
    s = item.get("structured") or {}
    if not s.get("recruiting"):
        return False
    end = s.get("end_date") or ""
    if not end:
        return True  # 수시모집일 수 있음
    try:
        end_dt = datetime.strptime(end, "%Y-%m-%d").date()
        today = datetime.strptime(TODAY, "%Y-%m-%d").date()
        return end_dt >= today
    except ValueError:
        return True


def crawl_all(max_pages: int = MAX_PAGES) -> list[dict]:
    """모든 페이지를 순회하며 전체 공고를 수집."""
    items: list[dict] = []
    seen_sns: set[str] = set()
    print(f"[crawl] nidview 전량 크롤 시작 (perPage={PER_PAGE})", file=sys.stderr)
    t0 = time.time()
    for page in range(1, max_pages + 1):
        data = fetch_page(page, PER_PAGE)
        if not data:
            break
        chunk = data.get("data") or []
        if not chunk:
            print(f"  page={page} 빈 응답 → 종료", file=sys.stderr)
            break
        for raw in chunk:
            norm = normalize_item(raw)
            sn = norm["pbancSn"]
            if not sn or sn in seen_sns:
                continue
            seen_sns.add(sn)
            items.append(norm)
        total = data.get("totalCount", 0)
        print(
            f"  page={page}: +{len(chunk)}건 (누적 {len(items)}/{total})",
            file=sys.stderr,
        )
        if len(chunk) < PER_PAGE:
            break
    elapsed = time.time() - t0
    print(f"[crawl] 전량 크롤 완료: {len(items)}건, {elapsed:.1f}초", file=sys.stderr)
    return items


# ══════════════════════════════════════════════════════════════
# update.py 호환 API (v5 signature 유지)
# ══════════════════════════════════════════════════════════════

def crawl(known_sns: set | None = None) -> list[dict]:
    """
    K-Startup 공고를 전량 수집한 뒤 **모집중** 공고만 반환.
    update.py 의 v5 crawl() 시그니처와 호환.

    Args:
        known_sns: update.py 가 이미 pool에 보유한 pbancSn 집합. v6에서는
                   전량 스캔이라 활용하지 않지만, 시그니처 호환을 위해 받는다.

    Returns:
        list of items, 각 item은 `structured` 필드 포함.
    """
    _ = known_sns  # v6에서는 활용 안 함 (전량 스캔 + 클라이언트 필터)
    all_items = crawl_all()
    before = len(all_items)
    active = [i for i in all_items if is_active(i)]
    print(
        f"[crawl] active 필터: {before} → {len(active)}건",
        file=sys.stderr,
    )
    # SN 내림차순 (최신 먼저)
    active.sort(
        key=lambda x: (x.get("structured") or {}).get("pbanc_sn_int") or 0,
        reverse=True,
    )
    return active


def main():
    ap = argparse.ArgumentParser(description="K-Startup 공고 크롤러 v6")
    ap.add_argument(
        "--out",
        default="crawl_results.json",
        help="결과 저장 경로 (기본: crawl_results.json)",
    )
    ap.add_argument(
        "--active-only",
        action="store_true",
        help="모집중(rcrt_prgs_yn=Y & 마감일 유효) 공고만 저장",
    )
    ap.add_argument(
        "--sample",
        type=int,
        default=0,
        help="디버그용: 첫 N페이지만 조회",
    )
    args = ap.parse_args()

    max_pages = args.sample if args.sample > 0 else MAX_PAGES
    all_items = crawl_all(max_pages=max_pages)

    if args.active_only:
        before = len(all_items)
        all_items = [i for i in all_items if is_active(i)]
        print(f"  active 필터: {before} → {len(all_items)}건", file=sys.stderr)

    all_items.sort(
        key=lambda x: (x.get("structured") or {}).get("pbanc_sn_int") or 0,
        reverse=True,
    )

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps(all_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[crawl] 저장: {out_path} ({len(all_items)}건)", file=sys.stderr)


if __name__ == "__main__":
    main()
