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

html = re.sub(
    r'const\s+now\s*=\s*new\s+Date\("\d{4}-\d{2}-\d{2}"\);',
    'const now = new Date(); now.setHours(0,0,0,0);',
    html,
)

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

footer = (
    '<div class="bottom-update" style="margin:24px auto 12px;max-width:1200px;'
    'padding:14px 18px;background:#f5f5f4;border:1px solid #e7e5e4;border-radius:10px;'
    'font-size:12.5px;color:#57534e;text-align:center;">'
    f'\U0001F552 <b>최근 업데이트 시각</b>: {updated_at} '
    f'· 누적 풀 <b>{total_pool}</b>건 '
    f'· 페이지 빌드 {build_now}'
    '</div>'
)

if 'class="bottom-update"' in html:
    html = re.sub(r'<div class="bottom-update"[^>]*>.*?</div>', footer, html, flags=re.DOTALL)
else:
    html = re.sub(r'</body>', footer + '\n</body>', html, count=1)

if html == original:
    print("No changes (already patched).")
else:
    INDEX.write_text(html, encoding="utf-8")
    print(f"✓ Patched index.html | updated_at={updated_at} pool={total_pool}")
