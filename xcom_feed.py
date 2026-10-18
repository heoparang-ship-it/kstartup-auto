#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent
XCOM_FILE = REPO / "xcom.json"
ORG = "주식회사 엑스컴"
SCHEMA = "xcom-feed-v1"
FIELDS = ("소프트웨어", "콘텐츠", "아트·예술", "행사")
REGION_ORDER = {"부평": 0, "인천": 1, "전국": 2}
SITE_LABEL = {
    "bizinfo": "BIZINFO",
    "kocca": "KOCCA",
    "itp": "ITP",
    "kstartup": "K-Startup",
}
FIELD_RULES = (
    (
        "소프트웨어",
        (
            "소프트웨어",
            "SW",
            "S/W",
            "SaaS",
            "인공지능",
            "AI",
            "앱개발",
            "플랫폼",
            "디지털전환",
            "정보화",
            "클라우드",
            "데이터",
            "IT ",
            " IT",
        ),
    ),
    (
        "콘텐츠",
        (
            "콘텐츠",
            "컨텐츠",
            "미디어",
            "영상",
            "방송",
            "크리에이터",
            "웹툰",
            "출판",
            "1인미디어",
        ),
    ),
    (
        "아트·예술",
        ("아트", "예술", "문화예술", "공연", "전시", "미술"),
    ),
    (
        "행사",
        (
            "행사",
            "페스티벌",
            "축제",
            "공모전",
            "해커톤",
            "데모데이",
            "컨퍼런스",
            "박람회",
        ),
    ),
)
EXCLUSIVE_REGIONS = (
    "부산",
    "대구",
    "광주",
    "대전",
    "울산",
    "세종",
    "강원",
    "충북",
    "충남",
    "전북",
    "전남",
    "경북",
    "경남",
    "제주",
    "서울",
    "경기",
)


def _blob_for_field(item: dict) -> str:
    s = item.get("structured") or {}
    return " ".join(
        str(x or "")
        for x in (
            item.get("title"),
            item.get("agency"),
            s.get("pldirSportRealmLclasCodeNm"),
            s.get("pldirSportRealmMlsfcCodeNm"),
            s.get("biz_class"),
            s.get("bsnsSumryCn"),
            s.get("content"),
            s.get("hashtags"),
        )
    )


def _blob_for_region(item: dict) -> str:
    s = item.get("structured") or {}
    return " ".join(
        str(x or "")
        for x in (item.get("title"), item.get("agency"), s.get("region"))
    )


def classify_field(item: dict) -> str | None:
    text = _blob_for_field(item)
    for field, kws in FIELD_RULES:
        if any(kw in text for kw in kws):
            return field
    return None


def classify_region_tier(item: dict) -> str | None:
    text = _blob_for_region(item)
    if "부평" in text:
        return "부평"
    if "인천" in text:
        return "인천"
    if any(r in text for r in EXCLUSIVE_REGIONS) and "전국" not in text:
        return None
    return "전국"


def site_of(item: dict) -> str:
    src = item.get("source")
    if src in SITE_LABEL:
        return SITE_LABEL[src]
    if str(item.get("pbancSn") or "").startswith("itp_"):
        return "ITP"
    return item.get("source_label") or "K-Startup"


def to_public_item(item: dict, collected_at: str) -> dict | None:
    field = classify_field(item)
    if field is None:
        return None
    region_tier = classify_region_tier(item)
    if region_tier is None:
        return None
    return {
        "title": item.get("title") or "",
        "agency": item.get("agency") or "",
        "site": site_of(item),
        "field": field,
        "region_tier": region_tier,
        "deadline": item.get("deadline") or "",
        "url": item.get("url") or "",
        "collected_at": collected_at,
    }


def build_feed(items: list, collected_at: str) -> dict:
    public = []
    for it in items:
        row = to_public_item(it, collected_at)
        if row is not None:
            public.append(row)
    public.sort(
        key=lambda r: (
            REGION_ORDER.get(r["region_tier"], 9),
            r.get("deadline") or "9999-99-99",
            r.get("title") or "",
        )
    )
    return {
        "schema": SCHEMA,
        "org": ORG,
        "collected_at": collected_at,
        "fields": list(FIELDS),
        "region_priority": ["부평", "인천", "전국"],
        "count": len(public),
        "items": public,
    }


def write_xcom_feed(items: list, now_kst: datetime, path: Path = XCOM_FILE) -> dict:
    collected_at = now_kst.strftime("%Y-%m-%dT%H:%M:%S+09:00")
    feed = build_feed(items, collected_at)
    path.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return feed
