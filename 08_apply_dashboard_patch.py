#!/usr/bin/env python3
"""kstartup-auto: index.html 에 P4 패치(PDF 점수 블록 6 + weights 정렬)를 안전하게 주입.

사용:
  python3 08_apply_dashboard_patch.py            # 패치 적용 (멱등성: 이미 적용됐으면 skip)
  python3 08_apply_dashboard_patch.py --dry-run  # 변경 미리보기
  python3 08_apply_dashboard_patch.py --revert   # 백업에서 복원

백업: index.html.before-p4 (한 번만 생성, 이후 적용 시 그대로 둠)
"""
from __future__ import annotations
import argparse, os, re, sys
from pathlib import Path

REPO = Path(os.environ.get("KSTARTUP_REPO", Path(__file__).resolve().parent))
INDEX = REPO / "index.html"
BACKUP = REPO / "index.html.before-p4"
SENTINEL = "/* === P4: PDF 기반 점수 블록 + 정렬 === */"

CSS_BLOCK = '''/* === P4: PDF 기반 점수 블록 + 정렬 === */
.pdf-score-block { background: #f5f3ff; border: 1px solid #d3adf7; border-radius: 8px; padding: 10px 12px; margin: 8px 0 0 0; font-size: 12px; }
.pdf-score-row { display: grid; grid-template-columns: 80px 1fr 60px; gap: 8px; align-items: center; margin: 3px 0; }
.pdf-score-label { color: #555; font-weight: 600; }
.pdf-score-bar { height: 8px; background: #e9e2f7; border-radius: 4px; overflow: hidden; }
.pdf-score-fill { height: 100%; background: linear-gradient(90deg, #b37feb, #722ed1); border-radius: 4px; }
.pdf-score-num { font-family: 'SF Mono', Menlo, monospace; text-align: right; color: #722ed1; font-weight: 700; }
.pdf-killer { color: #cf1322; font-size: 11px; margin-top: 6px; }
.pdf-killer-h { font-weight: 700; }
.pdf-evidence { color: #666; font-size: 11px; margin-top: 6px; padding-left: 8px; border-left: 2px solid #d3adf7; }
.pdf-evidence em { color: #722ed1; font-style: normal; }
.pdf-meta { color: #999; font-size: 10px; margin-top: 8px; }
.sort-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; background: white; padding: 8px 12px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.06); margin: 10px 0; font-size: 12.5px; }
.sort-bar .sb-h { font-weight: 700; color: #722ed1; margin-right: 4px; }
.sort-bar .sb-pri { background: #f5f3ff; color: #531dab; padding: 4px 10px; border-radius: 16px; }
.sort-bar .sb-edit { font-size: 11px; color: #999; margin-left: auto; }
.sort-bar .sb-edit code { background: #f5f5f5; padding: 1px 4px; border-radius: 3px; }
.score-chip { display: inline-block; background: #f9f0ff; color: #531dab; font-weight: 700; padding: 2px 8px; border-radius: 12px; font-size: 11px; margin-left: 4px; }'''

JS_HELPERS = '''// === P4: 가중치·정렬 ===
const DEFAULT_WEIGHTS = {
  weights: { pdf_pass_rate: 0.5, roi_score: 0.3, alternatives_richness: 0.2 },
  priority_labels: { pdf_pass_rate: "합격가능성", roi_score: "ROI", alternatives_richness: "대안" },
  fallback: { use_expected_pass_rate_when_pdf_missing: true, use_time_cost_hours_for_roi_when_pdf_missing: true, default_when_no_data: 0.0 }
};
let WEIGHTS_CONF = DEFAULT_WEIGHTS;
const SCORE_CACHE = new Map();
async function loadWeights() {
  try { const r = await fetch('weights.json', { cache: 'no-cache' }); if (r.ok) WEIGHTS_CONF = { ...DEFAULT_WEIGHTS, ...(await r.json()) }; } catch (_) {}
}
function altRichness(verdict) { const n = (verdict.alternatives || []).length; return Math.min(n, 3) / 3; }
function timeCostToRoi(hoursStr) {
  if (!hoursStr) return null;
  const m = String(hoursStr).match(/(\\d+)/g); if (!m) return null;
  const avg = m.length >= 2 ? (parseInt(m[0]) + parseInt(m[1])) / 2 : parseInt(m[0]);
  return Math.max(0, Math.min(1, 1 - avg / 100));
}
async function compositeScore(id) {
  if (SCORE_CACHE.has(id)) return SCORE_CACHE.get(id);
  const data = await loadAnalysis(id); const v = (data && data.verdict) || {}; const fb = WEIGHTS_CONF.fallback || {};
  let pdf_p = (typeof v.pdf_pass_rate === 'number') ? v.pdf_pass_rate
    : (fb.use_expected_pass_rate_when_pdf_missing && typeof v.expected_pass_rate === 'number') ? v.expected_pass_rate
    : (fb.default_when_no_data ?? 0);
  let roi = (typeof v.roi_score === 'number') ? v.roi_score
    : (fb.use_time_cost_hours_for_roi_when_pdf_missing && v.time_cost_hours) ? (timeCostToRoi(v.time_cost_hours) ?? (fb.default_when_no_data ?? 0))
    : (fb.default_when_no_data ?? 0);
  let alt = altRichness(v);
  const w = WEIGHTS_CONF.weights;
  const score = w.pdf_pass_rate * pdf_p + w.roi_score * roi + w.alternatives_richness * alt;
  const result = { score, pdf_p, roi, alt, has_pdf: typeof v.pdf_pass_rate === 'number' };
  SCORE_CACHE.set(id, result); return result;
}
async function sortItems(items) {
  await Promise.all(items.map(it => compositeScore(it.id)));
  return [...items].sort((a, b) => (SCORE_CACHE.get(b.id)?.score ?? 0) - (SCORE_CACHE.get(a.id)?.score ?? 0));
}
function renderSortBar() {
  const w = WEIGHTS_CONF.weights; const lbl = WEIGHTS_CONF.priority_labels;
  const ranked = Object.entries(w).sort((a, b) => b[1] - a[1]);
  const pills = ranked.map(([k, v], i) => `<span class="sb-pri">${i + 1}순위 ${lbl[k] || k} (${(v * 100).toFixed(0)}%)</span>`).join(' · ');
  const bar = document.getElementById('sort-bar');
  if (bar) bar.innerHTML = `<span class="sb-h">정렬</span>${pills}<span class="sb-edit"><code>weights.json</code> 수정 후 새로고침</span>`;
}
'''

PDF_BLOCK_JS = '''
  // 블록 6 — PDF 기반 점수 (verdict.pdf_pass_rate 있을 때만)
  let pdfBlockHtml = '';
  if (typeof v.pdf_pass_rate === 'number') {
    const evid = (v.pdf_pass_rate_evidence || []).slice(0, 3).map(e =>
      `<div class="pdf-evidence"><em>"${escapeHtml(e.quote || '')}"</em><br><span style="color:#999">— ${escapeHtml(e.source_pdf || '')}</span></div>`
    ).join('');
    const blockers = (v.killer_blockers || []).map(k => `<li>${escapeHtml(k)}</li>`).join('');
    const altsList = (v.alternatives || []).slice(0, 3).map(alt =>
      `<li><b>${escapeHtml(alt.title || alt.pbancSn || '')}</b>: ${escapeHtml(alt.reason || '')}</li>`
    ).join('');
    const rb = v.roi_breakdown || {};
    const rbBits = [];
    if (rb["지원금_만원"]) rbBits.push(`지원금 ${rb["지원금_만원"]}만원`);
    if (rb["자기부담_pct"] != null) rbBits.push(`자부담 ${(rb["자기부담_pct"] * 100).toFixed(0)}%`);
    else if (rb["자기부담_만원"]) rbBits.push(`자부담 ${rb["자기부담_만원"]}만원`);
    if (rb["작성공수_시간"]) rbBits.push(`작성 ${rb["작성공수_시간"]}h`);
    if (rb["인건비상한_만원"]) rbBits.push(`인건비상한 ${rb["인건비상한_만원"]}만원`);
    pdfBlockHtml = `
      <div class="aa-block pdf-score-block">
        <div class="aa-h">▸ PDF 기반 점수 ${v.one_liner_pdf ? `· ${escapeHtml(v.one_liner_pdf)}` : ''}</div>
        <div class="pdf-score-row"><span class="pdf-score-label">합격가능성</span><div class="pdf-score-bar"><div class="pdf-score-fill" style="width:${(v.pdf_pass_rate * 100).toFixed(0)}%"></div></div><span class="pdf-score-num">${(v.pdf_pass_rate * 100).toFixed(0)}%</span></div>
        ${typeof v.roi_score === 'number' ? `<div class="pdf-score-row"><span class="pdf-score-label">ROI</span><div class="pdf-score-bar"><div class="pdf-score-fill" style="width:${(v.roi_score * 100).toFixed(0)}%"></div></div><span class="pdf-score-num">${(v.roi_score * 100).toFixed(0)}%</span></div>` : ''}
        ${rbBits.length ? `<div style="font-size:11px;color:#666;margin-top:4px">${rbBits.join(' · ')}</div>` : ''}
        ${blockers ? `<div class="pdf-killer"><span class="pdf-killer-h">⚠ Killer:</span><ul class="aa-list">${blockers}</ul></div>` : ''}
        ${altsList ? `<div style="margin-top:6px"><div class="aa-h" style="font-size:10.5px;color:#722ed1">대안 (PDF 기반)</div><ul class="aa-list">${altsList}</ul></div>` : ''}
        ${evid ? `<div style="margin-top:6px"><div class="aa-h" style="font-size:10.5px;color:#722ed1">근거 인용</div>${evid}</div>` : ''}
        <div class="pdf-meta">${a.pdf_analyzed_at ? `PDF 점수 생성: ${escapeHtml(a.pdf_analyzed_at)} · ${escapeHtml(a.pdf_analyzer || 'sonnet-pdf@cowork')}` : ''}</div>
      </div>`;
  }
'''


def patch(html: str) -> tuple[str, list[str]]:
    log: list[str] = []
    if SENTINEL in html:
        log.append("이미 패치됨 — skip")
        return html, log

    # 1) CSS 주입: </style> 직전 (리터럴 replace — 한 번만)
    if "\n</style>" in html:
        html = html.replace("\n</style>", "\n" + CSS_BLOCK + "\n</style>", 1)
        log.append("CSS 주입 OK")
    else:
        log.append("⚠ </style> 못 찾음 — CSS 미적용")

    # 2) JS 헬퍼 주입: const TIER_EMOJI 직전. (앞에 거대 ITEMS 라인이 있으니 그 줄 끝~TIER 사이에 끼움)
    anchor = "\nconst TIER_EMOJI"
    if anchor in html:
        html = html.replace(anchor, "\n" + JS_HELPERS + "\nconst TIER_EMOJI", 1)
        log.append("JS 헬퍼 주입 OK")
    else:
        log.append("⚠ const TIER_EMOJI 진입점 못 찾음 — JS 헬퍼 미적용")

    # 3) renderAnalysis 안 블록6 주입 — `return natureHtml + ...` 직전
    target = "  return natureHtml + fitHtml + roiHtml + decHtml + altHtml + metaHtml;"
    if target in html:
        replacement = PDF_BLOCK_JS + "\n  return natureHtml + fitHtml + roiHtml + decHtml + altHtml + pdfBlockHtml + metaHtml;"
        html = html.replace(target, replacement)
        log.append("renderAnalysis 블록6 + return 패치 OK")
    else:
        log.append("⚠ renderAnalysis return 패턴 못 찾음")

    # 4) render() 함수를 async 로 + 정렬 추가
    target_fn = "function render() {\n  const container = document.getElementById(\"items\");\n  _currentFavs = getFavs();\n  const filtered = ITEMS.filter(it => {"
    if target_fn in html:
        replacement = "async function render() {\n  const container = document.getElementById(\"items\");\n  _currentFavs = getFavs();\n  const filtered = ITEMS.filter(it => {"
        html = html.replace(target_fn, replacement)
        log.append("render() async 변경 OK")
    else:
        log.append("⚠ render() 시그니처 못 찾음 — 정렬 비활성")

    # filtered.map → (await sortItems(filtered)).map
    target_render = 'container.innerHTML = filtered.map(renderCard).join("")'
    if target_render in html:
        html = html.replace(target_render, 'container.innerHTML = (await sortItems(filtered)).map(renderCard).join("")')
        log.append("render() 정렬 호출 주입 OK")
    else:
        log.append("⚠ filtered.map 호출 패턴 못 찾음")

    # 5) <body> 직후 sort-bar 영역
    target_body = "<body>\n"
    if target_body in html and 'id="sort-bar"' not in html:
        html = html.replace(target_body, '<body>\n<div id="sort-bar" class="sort-bar"></div>\n', 1)
        log.append("sort-bar 영역 주입 OK")

    # 6) 최초 render() 호출을 weights 로드 + sortBar 렌더로 대체 (리터럴 replace)
    if "loadWeights().then" not in html:
        # 가장 마지막 단독 render(); 호출 한 건만 교체
        last = html.rfind("\nrender();\n")
        if last == -1:
            last = html.rfind("\nrender();")
        if last != -1:
            replacement = "\nloadWeights().then(() => { renderSortBar(); render(); });\n"
            html = html[:last] + replacement + html[last + len("\nrender();\n"):]
            log.append("초기 render 부트스트랩 변경 OK")
        else:
            log.append("⚠ 마지막 render() 호출 못 찾음 — 수동 패치 필요")

    return html, log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()

    if not INDEX.exists():
        print(f"[ERROR] {INDEX} 없음", file=sys.stderr)
        return 1

    if args.revert:
        if not BACKUP.exists():
            print(f"[ERROR] 백업 없음: {BACKUP}", file=sys.stderr); return 1
        INDEX.write_bytes(BACKUP.read_bytes())
        print(f"[OK] {BACKUP.name} → {INDEX.name} 복원")
        return 0

    src = INDEX.read_text(encoding="utf-8")
    out, log = patch(src)
    print("[패치 로그]")
    for line in log: print(f"  - {line}")

    if args.dry_run:
        print(f"\n[dry-run] {len(out)-len(src):+d} bytes 변화 (적용 안 됨)")
        return 0

    if not BACKUP.exists():
        BACKUP.write_text(src, encoding="utf-8")
        print(f"[backup] {BACKUP.name} 생성")
    INDEX.write_text(out, encoding="utf-8")
    print(f"[OK] {INDEX.name} 갱신 ({len(out)-len(src):+d} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
