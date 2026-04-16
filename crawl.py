#!/usr/bin/env python3
"""
K-Startup 공고 크롤러 — RSS 피드 기반
- RSS 1회 호출로 모집중 공고 전체 수집 (300건+)
- 신규 공고만 상세 페이지에서 기관명 보강
- 기존 crawl.py 대비: HTTP 700회 → 1회 + α
"""
import json
import re
import sys
import requests
from xml.etree import ElementTree
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from html import unescape

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y-%m-%d")

RSS_URL = "https://www.k-startup.go.kr/web/contents/rss/bizpbanc-ongoing.do"
DETAIL_BASE = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KStartupBot/2.0)"}
MAX_DETAIL_WORKERS = 5


def fetch_rss() -> list[dict]:
    """RSS 피드에서 모집중 공고 전체를 가져온다."""
    r = requests.get(RSS_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    root = ElementTree.fromstring(r.text)

    items = []
    for entry in root.findall(".//item"):
        title_raw = entry.find("title").text or ""
        title = unescape(title_raw).strip()
        link = entry.find("link").text or ""
        pub_date = entry.find("pubDate").text or ""

        # pbancSn 추출 (link에서 id= 파라미터)
        sn_match = re.search(r"(?:pbancSn|id)=(\d+)", link)
        if not sn_match:
            continue
        pbanc_sn = sn_match.group(1)

        # 기관명: 제목에서 [기관명] 패턴 추출
        agency = ""
        agency_match = re.search(r"\[([^\]]+)\]", title)
        if agency_match:
            agency = agency_match.group(1).strip()

        items.append({
            "pbancSn": pbanc_sn,
            "title": title,
            "agency": agency,
            "deadline": "",  # RSS에 마감일 없음 — 상세페이지에서 보강 시도
            "url": f"{DETAIL_BASE}?schM=view&pbancSn={pbanc_sn}",
            "pub_date": pub_date,
        })

    return items


def fetch_detail_meta(sn: str) -> dict:
    """상세 페이지 og:title에서 기관명 보강을 시도한다."""
    url = f"{DETAIL_BASE}?schM=ALL&pbancSn={sn}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        # og:title에서 더 정확한 제목 추출
        m = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', r.text)
        og_title = unescape(m.group(1).strip()) if m else ""
        return {"pbancSn": sn, "og_title": og_title}
    except Exception:
        return {"pbancSn": sn, "og_title": ""}


def crawl(known_sns: set[str] | None = None) -> list[dict]:
    """
    RSS에서 전체 목록을 가져오고, 신규 공고의 상세 메타를 보강한다.
    known_sns: 이미 알고 있는 pbancSn 집합 (있으면 신규만 상세 조회)
    """
    print(f"[crawl] RSS 피드 호출...", file=sys.stderr)
    rss_items = fetch_rss()
    print(f"[crawl] RSS에서 {len(rss_items)}건 수집", file=sys.stderr)

    if known_sns is None:
        known_sns = set()

    # 신규 공고 중 기관명이 비어있는 것만 상세 조회
    new_without_agency = [
        it for it in rss_items
        if it["pbancSn"] not in known_sns and not it["agency"]
    ]

    if new_without_agency:
        print(f"[crawl] 신규 {len(new_without_agency)}건 상세 조회 중...", file=sys.stderr)
        detail_map = {}
        with ThreadPoolExecutor(max_workers=MAX_DETAIL_WORKERS) as pool:
            futures = {
                pool.submit(fetch_detail_meta, it["pbancSn"]): it["pbancSn"]
                for it in new_without_agency[:50]  # 최대 50건만
            }
            for f in as_completed(futures):
                result = f.result()
                if result["og_title"]:
                    detail_map[result["pbancSn"]] = result

        # og_title에서 기관명 보강
        for it in rss_items:
            if it["pbancSn"] in detail_map:
                og = detail_map[it["pbancSn"]]["og_title"]
                if not it["agency"]:
                    am = re.search(r"\[([^\]]+)\]", og)
                    if am:
                        it["agency"] = am.group(1).strip()

    return rss_items


if __name__ == "__main__":
    # 단독 실행: JSON 출력
    known = set()
    if len(sys.argv) >= 2:
        try:
            with open(sys.argv[1], "r", encoding="utf-8") as f:
                pool = json.load(f)
            known = {it["pbancSn"] for it in pool.get("items", []) if it.get("pbancSn")}
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    items = crawl(known)
    json.dump(items, sys.stdout, ensure_ascii=False, indent=2)
