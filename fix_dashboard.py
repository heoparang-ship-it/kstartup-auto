#!/usr/bin/env python3
import re, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

INDEX = Path("index.html")
RECS  = Path("recommendations.json")
if not INDEX.exists():
    sys.exit("ERROR: index.html not found.")

html = INDEX.read_text(encoding="utf-8")
original = html

# 패치 1: D-day 실시간화
html = re.sub(
    r'const\s+now\s*=\s*new\s+Date\(["\x27]\d{4}-\d{2}-\d{2}["\x27]\)\s*;?',
    'const now = new Date(); now.setHours(0,0,0,0);',
    html,
)

# recommendations.json에서 데이터
updated_at = "(unknown)"; total_pool = "?"
if RECS.exists():
    try:
        rec = json.loads(RECS.read_text(encoding="utf-8"))
        updated_at = rec.get("updated_at_kst") or "(unknown)"
        total_pool = str(len(rec.get("items", [])))
    except Exception as e:
        print(f"WARN: {e}")

kst = timezone(timedelta(hours=9))
build_now = datetime.now(kst).strftime("%Y-%m-%d %H:%M KST")

# 상단 배너 (눈에 잘 띄는 노란색 띠 형태)
top_block = (
    '<div class="top-update" style="margin:0 auto;max-width:none;'
    'padding:10px 18px;background:#fef3c7;border-bottom:2px solid #fcd34d;'
    'font-size:13px;color:#78350f;text-align:center;font-weight:500;">'
    f'\U0001F552 <b>최근 업데이트 시각</b>: {updated_at} '
    f'· 누적 풀 <b>{total_pool}</b>건 '
    f'· 페이지 빌드 {build_now}'
    '</div>'
)

# 기존 하단 bottom-update 제거 (중복 방지)
html = re.sub(r'\n?<div class="bottom-update"[^>]*>.*?</div>\n?', '\n', html, flags=re.DOTALL)
# 기존 top-update 있으면 교체, 없으면 <body ...> 직후 삽입
if 'class="top-update"' in html:
    html = re.sub(r'<div class="top-update"[^>]*>.*?</div>', top_block, html, flags=re.DOTALL)
else:
    html = re.sub(r'(<body[^>]*>)', r'\1\n' + top_block, html, count=1)

if html == original:
    print("No changes (already patched).")
else:
    INDEX.write_text(html, encoding="utf-8")
    print(f"✓ Patched index.html | updated_at={updated_at} pool={total_pool}")
