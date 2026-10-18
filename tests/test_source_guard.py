#!/usr/bin/env python3
from __future__ import annotations

import unittest

from source_guard import count_by_source, find_drops, source_of
from update import expire_stale, load_pool
from xcom_feed import build_feed, classify_field, classify_region_tier


class SourceGuardTests(unittest.TestCase):
    def test_drop_at_half_fails(self) -> None:
        drops = find_drops({"bizinfo": 1207, "kstartup": 231}, {"bizinfo": 0, "kstartup": 231})
        self.assertTrue(any(d.startswith("bizinfo:") for d in drops))
        self.assertFalse(any(d.startswith("kstartup:") for d in drops))

    def test_exactly_half_is_a_drop(self) -> None:
        drops = find_drops({"bizinfo": 100}, {"bizinfo": 50})
        self.assertTrue(drops)
        self.assertEqual(find_drops({"bizinfo": 100}, {"bizinfo": 51}), [])

    def test_stale_skips_sources_not_crawled(self) -> None:
        items = [
            {"title": "keep bizinfo", "source": "bizinfo", "last_seen": "2026-01-01"},
            {"title": "drop kstartup", "source": "kstartup", "last_seen": "2026-01-01"},
        ]
        kept, expired = expire_stale(items, {"kstartup"})
        titles = [it["title"] for it in kept]
        self.assertIn("keep bizinfo", titles)
        self.assertEqual(expired, ["drop kstartup (stale)"])

    def test_load_pool_raises_on_schema_mismatch(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        import update as u

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "recommendations.json"
            path.write_text(json.dumps({"schema_version": 99, "items": [{"id": "x"}]}), encoding="utf-8")
            old = u.POOL_FILE
            u.POOL_FILE = str(path)
            try:
                with self.assertRaises(ValueError):
                    load_pool()
            finally:
                u.POOL_FILE = old

    def test_count_treats_itp_prefix(self) -> None:
        items = [
            {"source": "bizinfo"},
            {"pbancSn": "itp_1"},
            {"pbancSn": "123"},
        ]
        self.assertEqual(source_of(items[1]), "itp")
        self.assertEqual(count_by_source(items), {"bizinfo": 1, "itp": 1, "kstartup": 1})


class XcomFeedTests(unittest.TestCase):
    def test_field_and_bupyeong_first(self) -> None:
        items = [
            {
                "title": "전국 SW 지원",
                "agency": "중기부",
                "source": "bizinfo",
                "deadline": "2026-12-01",
                "url": "https://example.com/a",
                "structured": {"pldirSportRealmLclasCodeNm": "기술"},
            },
            {
                "title": "부평구 콘텐츠 공모",
                "agency": "부평구청",
                "source": "kstartup",
                "deadline": "2026-11-01",
                "url": "https://example.com/b",
                "structured": {},
            },
            {
                "title": "부산 전용 금융",
                "agency": "부산테크노파크",
                "source": "bizinfo",
                "deadline": "2026-10-20",
                "url": "https://example.com/c",
                "structured": {},
            },
        ]
        self.assertEqual(classify_field(items[0]), "소프트웨어")
        self.assertEqual(classify_region_tier(items[1]), "부평")
        self.assertIsNone(classify_region_tier(items[2]))
        feed = build_feed(items, "2026-10-18T23:00:00+09:00")
        self.assertEqual([r["region_tier"] for r in feed["items"]], ["부평", "전국"])
        self.assertEqual(feed["items"][0]["field"], "콘텐츠")
        self.assertEqual(set(feed["items"][0]), {
            "title", "agency", "site", "field", "region_tier", "deadline", "url", "collected_at",
        })


if __name__ == "__main__":
    unittest.main()
