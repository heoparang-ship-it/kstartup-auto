#!/usr/bin/env python3
"""fix_dashboard.py — kstartup-auto 대시보드 후처리 (즐겨찾기 보존 모드)
- D-day 실시간화
- 상단 노란 배너 (최근 업데이트 시각)
- 만료 공고는 풀에 보존 (즐겨찾기 영구 보관 위해)
- 화면에서는 만료+!즐겨찾기 항목 자동 숨김 (즐겨찾기는 만료돼도 계속 표시)
"""
import re, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

INDEX = Path("index.html")
RECS  = Path("recommendations.json")
if not INDEX.exists():
    sys.exit("ERROR: index.html not found.")

kst = timezone(timedelta(hours=9))
now = datetime.now(kst)
build_now = now.strftime("%Y-%m-%d %H:%M KST")

recs_data = None
if RECS.exists():
    try:
        recs_data = json.loads(RECS.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"WARN recs: {e}")

html = INDEX.read_text(encoding="utf-8")
original = html

# ─── 1. D-day 실시간화 ─────────────────────────────────────────────
html = re.sub(
    r'const\s+now\s*=\s*new\s+Date\(["\x27]\d{4}-\d{2}-\d{2}["\x27]\)\s*;?',
    'const now = new Date(); now.setHours(0,0,0,0);',
    html,
)

# ─── 2. render() 필터에 "만료 + 즐겨찾기 아님 = 숨김" 한 줄 주입 ───
EXPIRED_FILTER = '    if (it.deadline && new Date(it.deadline + "T23:59:59+09:00") < new Date() && !_currentFavs.has(it.id)) return false;\n'
fav_filter_line = '    if (state.fav === "only" && !_currentFavs.has(it.id)) return false;'
if EXPIRED_FILTER.strip() not in html:
    if fav_filter_line in html:
        html = html.replace(fav_filter_line, EXPIRED_FILTER + fav_filter_line, 1)
        print("  ✓ 만료 숨김 필터 주입 (즐겨찾기는 예외)")
    else:
        print("  ⚠ fav 필터 라인 못찾음 — 수동 확인 필요")
else:
    print("  · 만료 숨김 필터 이미 적용됨")

# ─── 3. 상단 노란 배너 ─────────────────────────────────────────────
updated_at = recs_data.get("updated_at_kst") if recs_data else "(unknown)"
total_pool = str(len(recs_data.get("items", []))) if recs_data else "?"
top_block = (
    '<div class="top-update" style="margin:0 auto;max-width:none;'
    'padding:10px 18px;background:#fef3c7;border-bottom:2px solid #fcd34d;'
    'font-size:13px;color:#78350f;text-align:center;font-weight:500;">'
    f'\U0001F552 <b>최근 업데이트 시각</b>: {updated_at} '
    f'· 누적 풀 <b>{total_pool}</b>건 '
    f'· 페이지 빌드 {build_now} '
    f'· 만료 공고는 ★ 즐겨찾기만 보관됩니다'
    '</div>'
)
html = re.sub(r'\n?<div class="bottom-update"[^>]*>.*?</div>\n?', '\n', html, flags=re.DOTALL)
if 'class="top-update"' in html:
    html = re.sub(r'<div class="top-update"[^>]*>.*?</div>', top_block, html, flags=re.DOTALL)
else:
    html = re.sub(r'(<body[^>]*>)', r'\1\n' + top_block, html, count=1)

# ─── 4. 저장 ───────────────────────────────────────────────────────
if html == original:
    print("No changes.")
else:
    INDEX.write_text(html, encoding="utf-8")
    print(f"✓ Patched | updated_at={updated_at} pool={total_pool}")
    print("  주의: 만료 공고는 풀에서 삭제하지 않음 (즐겨찾기 영구 보관)")
