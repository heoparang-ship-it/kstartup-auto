#!/usr/bin/env python3
"""
인천테크노파크(ITP) 지원사업 게시판 크롤러
─────────────────────────────────────────
대상: https://itp.or.kr/intro.asp?tmid=13 (지원사업, 모집중만)

전략:
- 목록 페이지(`?tmid=13&PageNum=N`)에서 한 페이지당 10건 파싱
- alt='진행중' 항목만 추출하고, 마감 페이지가 나오면 정지
- 각 항목 상세 페이지(`?tmid=13&seq=<N>`)에서 마감일·첨부 추출
- 반환 항목 형식은 update.py 호환 (pbancSn → itp_<seq> 사용)

update.py 통합:
- known_sns 에 "itp_<seq>" 형식 ID가 들어 있으면 dedup 처리됨
- classify() 호출 전에 update.py에서 ITP 항목은 classify_itp_dept()로 우회
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y-%m-%d")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
LIST_URL = "https://itp.or.kr/intro.asp?tmid=13"
DETAIL_URL_TMPL = "https://itp.or.kr/intro.asp?tmid=13&seq={seq}"
LIST_TIMEOUT = 20
DETAIL_TIMEOUT = 25
LIST_MAX_PAGES = 12  # 안전 캡 (보통 4~6페이지에서 끊김)
DETAIL_PARALLEL = 8


def _fetch(url: str, timeout: int = LIST_TIMEOUT) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": LIST_URL,
        "Accept": "text/html,application/xhtml+xml",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def _parse_list(html: str) -> list[dict]:
    rows = []
    m = re.search(r"<tbody>(.*?)</tbody>", html, re.S)
    if not m:
        return rows
    body = m.group(1)
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        seq_m = re.search(r"fncShow\('?(\d+)'?\)", tr)
        if not seq_m:
            continue
        no_m = re.search(r"<td>(\d+)</td>", tr)
        dept_m = re.search(r'<td class="subjectc">(.*?)</td>', tr, re.S)
        title_m = re.search(r"<a [^>]*>(.*?)</a>", tr, re.S)
        date_m = re.search(r'<td class="idWriteDateData">\s*(\d{4}-\d{2}-\d{2})', tr)
        status_m = re.search(r"alt='([^']+)'", tr)
        rows.append({
            "no": int(no_m.group(1)) if no_m else None,
            "dept": re.sub(r"<.*?>", "", dept_m.group(1)).strip() if dept_m else "",
            "seq": seq_m.group(1),
            "title": re.sub(r"<.*?>|&nbsp;", "", title_m.group(1)).strip() if title_m else "",
            "write_date": date_m.group(1) if date_m else "",
            "status": status_m.group(1) if status_m else "",
        })
    return rows


def _parse_detail(html: str) -> dict:
    clean = re.sub(r"<img[^>]+>", "", html)
    out = {"deadline": "", "attachments": []}
    dts = re.findall(
        r"<dt[^>]*>\s*(?:<span[^>]*>)?\s*([^<]+?)\s*(?:</span>)?\s*</dt>"
        r"\s*<dd[^>]*>\s*(.*?)\s*</dd>",
        clean, re.S,
    )
    for label, val in dts:
        v = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", val)).strip()
        if "진행상태" in label:
            md = re.search(r"마감일?\s*(\d{4}-\d{2}-\d{2})", v)
            if md:
                out["deadline"] = md.group(1)
        elif "첨부파일" in label:
            out["attachments"] = re.findall(
                r"붙임\s*\d+\.[^<]+?\([\d.]+KB\)|첨부\s*\d+\.[^<]+?\([\d.]+KB\)",
                val,
            )
    return out


def _crawl_list_pages() -> list[dict]:
    """모든 페이지에서 진행중 항목 수집. 한 페이지에 진행중이 0개면 정지."""
    all_rows: list[dict] = []
    for page in range(1, LIST_MAX_PAGES + 1):
        url = LIST_URL if page == 1 else f"{LIST_URL}&PageNum={page}"
        try:
            html = _fetch(url, timeout=LIST_TIMEOUT)
        except Exception as e:
            print(f"[itp] list page {page} fetch error: {e}", file=sys.stderr)
            break
        rows = _parse_list(html)
        if not rows:
            break
        recruit = [r for r in rows if r["status"] == "진행중"]
        all_rows.extend(rows)
        # 한 페이지의 진행중이 0건이면 더 이상 가지 않음
        if not recruit:
            break
        time.sleep(0.3)
    # 진행중만, dedup
    seen = set()
    uniq = []
    for r in all_rows:
        if r["status"] != "진행중":
            continue
        if r["seq"] in seen:
            continue
        seen.add(r["seq"])
        uniq.append(r)
    return uniq


def _enrich_detail(rec: dict) -> dict:
    try:
        html = _fetch(DETAIL_URL_TMPL.format(seq=rec["seq"]), timeout=DETAIL_TIMEOUT)
        rec.update(_parse_detail(html))
    except Exception as e:
        rec["fetch_error"] = str(e)[:80]
    return rec


def _to_pool_item(rec: dict) -> dict:
    """update.py 메인 풀에 들어갈 dict로 변환. pbancSn에 itp_<seq> 사용."""
    return {
        "pbancSn": f"itp_{rec['seq']}",
        "title": rec.get("title", "").strip(),
        "agency": f"인천테크노파크 {rec.get('dept','').strip()}".strip(),
        "deadline": rec.get("deadline", ""),
        "url": DETAIL_URL_TMPL.format(seq=rec["seq"]),
        "first_seen": rec.get("write_date", "") or TODAY,
        "last_seen": TODAY,
        "structured": {
            "source_kind": "itp",
            "itp_seq": rec["seq"],
            "itp_dept": rec.get("dept", ""),
            "attachments": rec.get("attachments", []),
            "recruiting": True,
            "region": "인천",
        },
    }


def crawl(known_sns: set | None = None) -> list[dict]:
    """update.py 호환 인터페이스. known_sns에 'itp_<seq>'가 있으면 스킵하지 않고 갱신."""
    if known_sns is None:
        known_sns = set()
    print("[itp] 목록 페이지 크롤 시작", file=sys.stderr)
    rows = _crawl_list_pages()
    print(f"[itp] 진행중 {len(rows)}건 → 상세 페이지 fetch", file=sys.stderr)
    if not rows:
        return []

    detailed: list[dict] = []
    with ThreadPoolExecutor(max_workers=DETAIL_PARALLEL) as ex:
        futures = [ex.submit(_enrich_detail, r) for r in rows]
        for fut in as_completed(futures):
            detailed.append(fut.result())

    # 마감일 없거나 fetch error 항목은 제외
    valid = [r for r in detailed if r.get("deadline") and not r.get("fetch_error")]
    if len(valid) < len(detailed):
        skipped = len(detailed) - len(valid)
        print(f"[itp] 마감일 미확보·fetch error로 {skipped}건 제외", file=sys.stderr)
    print(f"[itp] 풀 형식으로 변환 → {len(valid)}건", file=sys.stderr)

    # update.py 형식으로 변환
    return [_to_pool_item(r) for r in valid]


# ── ITP 부서별 분류 룰 ────────────────────────────────────────
# update.py의 classify() 우회 — itp_ 항목만 이 함수 사용
DEPT_RULES = {
    'AI혁신센터':           ('green',  '인천 매칭 + AI (sinhon.life Claude PWA / 엑스컴 SW)'),
    '콘텐츠기업지원센터':   ('green',  '인천 매칭 + 콘텐츠 (sinhon.life 허브 + 56만조회)'),
    '문화콘텐츠센터':       ('green',  '인천 매칭 + 문화콘텐츠'),
    '디지털기술융합센터':   ('green',  '인천 매칭 + 디지털 SW (엑스컴 정보통신)'),
    '혁신창업센터':         ('green',  '인천 매칭 + 창업 일반'),
    '스타트업파크센터':     ('green',  '인천 매칭 + 스타트업파크 (엑스컴 부평 본점)'),
    '벤처투자지원센터':     ('green',  '인천 매칭 + 투자 (IR 단계)'),
    '마케팅센터':           ('green',  '인천 매칭 + 마케팅 그로스'),
    '디자인지원센터':       ('yellow', '인천 매칭 + 디자인 (UI/콘텐츠 부분 매칭)'),
    '경영지원센터':         ('yellow', '인천 매칭 + 경영자금'),
    '경영지원본부':         ('yellow', '인천 매칭 + 경영지원'),
    '수출지원센터':         ('yellow', '인천 매칭 + 수출 (글로벌 단계)'),
    '제물포스마트타운':     ('yellow', '인천 매칭 + 입주공간'),
    '디자인교육센터':       ('orange', '인천 매칭이지만 디자인 교육 — 사업 매칭 약함'),
    '환경디자인센터':       ('orange', '인천 매칭이지만 환경디자인 매칭 약함'),
    '제조혁신센터':         ('orange', '인천 매칭이지만 제조 분야 — SW 불일치'),
    '바이오센터':           ('orange', '인천 매칭이지만 바이오 분야 불일치'),
    '녹색반도체센터':       ('orange', '인천 매칭이지만 반도체 분야 불일치'),
    '미래에너지센터':       ('orange', '인천 매칭이지만 에너지 분야 불일치'),
    '미래차센터':           ('orange', '인천 매칭이지만 모빌리티 불일치'),
    '항공센터':             ('orange', '인천 매칭이지만 항공 불일치'),
    '로봇센터':             ('orange', '인천 매칭이지만 로봇 불일치'),
    '파브센터':             ('orange', '인천 매칭이지만 파브/PAV 불일치'),
    '고용안정센터':         ('orange', '인천 매칭이지만 고용 — 사업 본체 약함'),
    '청년일자리센터':       ('orange', '인천 매칭이지만 일자리 — 사업 본체 약함'),
    '뿌리산업일자리센터':   ('orange', '인천 매칭이지만 일자리 + 뿌리산업 불일치'),
    '일자리센터':           ('orange', '인천 매칭이지만 일자리 — 사업 본체 약함'),
}


def classify_itp(item: dict) -> tuple[str, dict]:
    """ITP 항목 전용 분류기. (tier, evidence) 반환."""
    struct = item.get("structured", {}) or {}
    dept = (struct.get("itp_dept") or "").strip()
    tier, reason = DEPT_RULES.get(dept, ("yellow", f"인천 ITP {dept or '미상'} 부서"))
    evidence = {
        "summary_reason": reason,
        "category_hints": ["incheon", "itp"] + ([dept] if dept else []),
        "rule_checks": {
            "recruiting": {"pass": True, "value": "True", "detail": "ITP 진행중 항목"},
            "deadline": {
                "pass": bool(item.get("deadline")),
                "value": item.get("deadline", ""),
                "detail": "ITP 마감일",
            },
            "region": {"pass": True, "value": "인천", "detail": "ITP=인천 거점"},
        },
        "axis_scores": {
            "region": "green",
            "stage": "green",
            "industry": tier,
            "nature": tier,
            "qualification": "green",
        },
        "exclusion_flags": [],
        "audit_flags": [],
        "tier_logic": f"ITP {dept} 부서별 룰 → {tier}",
        "classify_version": "v8.3-itp",
    }
    return tier, evidence


if __name__ == "__main__":
    items = crawl(set())
    print(json.dumps(items[:3], ensure_ascii=False, indent=2))
    print(f"\nTotal: {len(items)}")
    by_tier = {}
    for it in items:
        t, _ = classify_itp(it)
        by_tier[t] = by_tier.get(t, 0) + 1
    print("Tier breakdown:", by_tier)
