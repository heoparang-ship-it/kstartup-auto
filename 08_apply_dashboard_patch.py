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
SENTINEL_V2 = "/* === P4 v2: tier_revised badge === */"
SENTINEL_V3 = "/* === P4 v3: 합격률 칩 + PDF 블록 최상단 === */"
SENTINEL_V4 = "/* === P4 v4: 점수화 대기 배지 + 신청 상태 === */"
SENTINEL_V5 = "/* === P4 v5: 결정 필터(GO/조건부/NO-GO) === */"
SENTINEL_V6 = "/* === P4 v6: 신규 공고 NEW 배지 === */"

CSS_BLOCK = '''/* === P4: PDF 기반 점수 블록 + 정렬 === */
/* === P4 v2: tier_revised badge === */
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
.score-chip { display: inline-block; background: #f9f0ff; color: #531dab; font-weight: 700; padding: 2px 8px; border-radius: 12px; font-size: 11px; margin-left: 4px; }
/* P4 v2: tier_revised badge */
.tier-revised-badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 10.5px; font-weight: 700; margin-left: 4px; vertical-align: middle; }
.tier-revised-up   { background: #d9f7be; color: #389e0d; }
.tier-revised-down { background: #fff1f0; color: #cf1322; }
.tier-revised-same { background: #f0f5ff; color: #1d39c4; }
.tier-revised-badge::before { margin-right: 3px; }
.tier-revised-up::before   { content: "🔼"; }
.tier-revised-down::before { content: "🔽"; }
.tier-revised-same::before { content: "✓"; }
.sb-revised-stats { font-size: 11px; color: #722ed1; padding-left: 8px; border-left: 1px solid #d9d9d9; margin-left: 8px; }'''

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
  if (bar) bar.innerHTML = `<span class="sb-h">정렬</span>${pills}<span class="sb-revised-stats" id="tier-revised-stats">tier 변동 집계 중…</span><span class="sb-edit"><code>weights.json</code> 수정 후 새로고침</span>`;
}

// P4 v2: 카드 헤더의 .badges 에 tier_revised 배지 비동기 추가
const TIER_RANK = { red: 0, orange: 1, yellow: 2, green: 3 };
async function loadTierRevisedBadge(itemId) {
  const data = await loadAnalysis(itemId);
  const v = (data && data.verdict) || {};
  const rev = v.tier_revised;
  if (!rev) return;
  let badges;
  try { badges = document.querySelector(`.item[data-id="${CSS.escape(itemId)}"] .badges`); } catch (_) { return; }
  if (!badges || badges.querySelector('.tier-revised-badge')) return;
  const item = ITEMS.find(i => i.id === itemId);
  const cur = item?.tier;
  const cls = TIER_RANK[rev] > TIER_RANK[cur] ? 'tier-revised-up'
            : TIER_RANK[rev] < TIER_RANK[cur] ? 'tier-revised-down' : 'tier-revised-same';
  const label = TIER_RANK[rev] === TIER_RANK[cur] ? `PDF: ${rev}` : `${cur}→${rev}`;
  const span = document.createElement('span');
  span.className = `tier-revised-badge ${cls}`;
  span.textContent = label;
  span.title = v.tier_revised_reason || '';
  badges.appendChild(span);
}

async function updateTierRevisedStats() {
  const stats = { up: 0, down: 0, same: 0, none: 0 };
  await Promise.all(ITEMS.map(async (it) => {
    const data = await loadAnalysis(it.id);
    const rev = data?.verdict?.tier_revised;
    if (!rev) { stats.none += 1; return; }
    const d = TIER_RANK[rev] - TIER_RANK[it.tier];
    if (d > 0) stats.up += 1;
    else if (d < 0) stats.down += 1;
    else stats.same += 1;
  }));
  const el = document.getElementById('tier-revised-stats');
  if (el) el.innerHTML = `tier 변동: 🔼 ${stats.up} · 🔽 ${stats.down} · ✓ ${stats.same} (PDF 미평가 ${stats.none})`;
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


V6_CSS = """/* === P4 v6: 신규 공고 NEW 배지 === */
.new-badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 700; margin-left: 4px; vertical-align: middle; background: linear-gradient(135deg, #ff7875, #f5222d); color: white; box-shadow: 0 1px 3px rgba(245, 34, 45, 0.3); }
.new-badge::before { content: "🆕 "; }
.sb-new-stats { font-size: 11.5px; color: #cf1322; padding-left: 8px; border-left: 1px solid #d9d9d9; margin-left: 8px; font-weight: 700; cursor: help; }
.sb-new-stats:empty { display: none; }
.item.is-new { border-left: 3px solid #f5222d; }
"""

V6_JS = """// === P4 v6: 신규 공고 NEW 배지 ===
const NEW_WINDOW_DAYS = 3;
function isItemNew(item) {
  const ct = item && item.structured && item.structured.creatPnttm;
  if (!ct) return false;
  try {
    const dt = new Date(String(ct).replace(' ', 'T'));
    if (isNaN(dt.getTime())) return false;
    const age = (Date.now() - dt.getTime()) / 86400000;
    return age >= 0 && age <= NEW_WINDOW_DAYS;
  } catch { return false; }
}
function loadNewBadge(itemId) {
  const item = ITEMS.find(i => i.id === itemId);
  if (!item || !isItemNew(item)) return;
  let card, badges;
  try {
    card = document.querySelector(`.item[data-id="${CSS.escape(itemId)}"]`);
    badges = card?.querySelector('.badges');
  } catch { return; }
  if (!badges || badges.querySelector('.new-badge')) return;
  card.classList.add('is-new');
  const span = document.createElement('span');
  span.className = 'new-badge';
  span.textContent = 'NEW';
  span.title = `${NEW_WINDOW_DAYS}일 이내 게시 — ${item.structured?.creatPnttm || ''}`;
  badges.appendChild(span);
}
async function updateNewStats() {
  let newAll = 0, newPending = 0;
  await prefetchAllAnalysis();
  ITEMS.forEach(it => {
    if (isItemNew(it)) {
      newAll += 1;
      const v = AA_CACHE.get(it.id)?.verdict;
      if (typeof v?.pdf_pass_rate !== 'number') newPending += 1;
    }
  });
  const el = document.getElementById('new-stats');
  if (!el) return;
  if (newAll === 0) { el.innerHTML = ''; el.title = ''; return; }
  el.innerHTML = newPending > 0
    ? `🆕 신규 <b>${newAll}</b>건 (점수화 대기 <b>${newPending}</b>)`
    : `🆕 신규 <b>${newAll}</b>건 (모두 점수화됨)`;
  el.title = `최근 ${NEW_WINDOW_DAYS}일 이내 게시된 공고 ${newAll}건` +
    (newPending > 0 ? ` — ${newPending}건은 Cowork 세션에서 점수화 필요` : '');
}
"""

V5_CSS = """/* === P4 v5: 결정 필터(GO/조건부/NO-GO) === */
.decision-filter { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; padding: 6px 12px; background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.06); margin: 8px 0; }
.dec-label { font-size: 11px; color: #999; text-transform: uppercase; letter-spacing: 0.05em; margin-right: 4px; }
.dec-btn { padding: 5px 12px; border: 1px solid #e0dcd7; background: white; border-radius: 16px; cursor: pointer; font-size: 12.5px; }
.dec-btn:hover { background: #fafafa; }
.dec-btn.active { font-weight: 700; border-color: transparent; color: white; }
.dec-btn.active[data-decision="all"]    { background: #595959; }
.dec-btn.active[data-decision="go"]     { background: #389e0d; }
.dec-btn.active[data-decision="strict"] { background: #237804; }
.dec-btn.active[data-decision="cond"]   { background: #d46b08; }
.dec-btn.active[data-decision="nogo"]   { background: #cf1322; }
.dec-btn .dec-count { font-size: 10.5px; opacity: 0.7; margin-left: 3px; }
.dec-btn.active .dec-count { opacity: 0.95; }
"""

V5_JS = """// === P4 v5: 결정 필터(GO/조건부/NO-GO) ===
function normalizeDecision(verdict) {
  // 기존 verdict.decision (rule-based) + tier_revised (PDF 기반) 통합 정규화
  if (!verdict) return 'unknown';
  const dec = String(verdict.decision || '').toUpperCase();
  const rev = verdict.tier_revised;
  // PDF 점수가 강력하게 NO-GO면 우선
  if (typeof verdict.pdf_pass_rate === 'number') {
    if (verdict.pdf_pass_rate < 0.1) return 'nogo';
    if (verdict.pdf_pass_rate >= 0.5) return 'go';
    if (verdict.pdf_pass_rate >= 0.2 || rev === 'yellow' || rev === 'orange') return 'cond';
  }
  // PDF 점수 없으면 기존 decision 만 본다
  if (dec.includes('NO-GO') || dec.includes('NOGO') || dec === 'NO GO') return 'nogo';
  if (dec.includes('CONDITIONAL') || dec.includes('조건부') || dec.endsWith('-?')) return 'cond';
  if (dec.startsWith('GO')) return 'go';
  return 'unknown';
}
function matchDecision(verdict, mode) {
  if (!mode || mode === 'all') return true;
  const norm = normalizeDecision(verdict);
  if (mode === 'go')     return norm === 'go' || norm === 'cond';   // GO + 조건부
  if (mode === 'strict') return norm === 'go';
  if (mode === 'cond')   return norm === 'cond';
  if (mode === 'nogo')   return norm === 'nogo';
  return true;
}
async function prefetchAllAnalysis() {
  // 백그라운드로 모든 deep_analysis 캐시. 진행 중에 사용자가 필터 누르면 await 보장.
  return Promise.all(ITEMS.map(it => loadAnalysis(it.id)));
}
async function ensureAnalysisReady() {
  await prefetchAllAnalysis();
}
function renderDecisionFilter() {
  if (document.getElementById('decision-filter')) return;
  const sortBar = document.getElementById('sort-bar');
  if (!sortBar || !sortBar.parentElement) return;
  const grp = document.createElement('div');
  grp.id = 'decision-filter';
  grp.className = 'decision-filter';
  grp.innerHTML = `
    <span class="dec-label">결정</span>
    <button class="dec-btn active" data-decision="all">전체 <span class="dec-count" id="dec-cnt-all"></span></button>
    <button class="dec-btn" data-decision="go">✅ GO + 조건부 <span class="dec-count" id="dec-cnt-go"></span></button>
    <button class="dec-btn" data-decision="strict">✅ GO 만 <span class="dec-count" id="dec-cnt-strict"></span></button>
    <button class="dec-btn" data-decision="cond">🤔 조건부 <span class="dec-count" id="dec-cnt-cond"></span></button>
    <button class="dec-btn" data-decision="nogo">🚫 NO-GO <span class="dec-count" id="dec-cnt-nogo"></span></button>
  `;
  sortBar.parentElement.insertBefore(grp, sortBar.nextSibling);
  grp.querySelectorAll('.dec-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      grp.querySelectorAll('.dec-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.decision = btn.dataset.decision;
      render();
    });
  });
}
async function updateDecisionCounts() {
  await prefetchAllAnalysis();
  const counts = { all: ITEMS.length, go: 0, strict: 0, cond: 0, nogo: 0, unknown: 0 };
  ITEMS.forEach(it => {
    const v = AA_CACHE.get(it.id)?.verdict;
    const n = normalizeDecision(v);
    if (n === 'go')      { counts.strict += 1; counts.go += 1; }
    else if (n === 'cond'){ counts.cond += 1; counts.go += 1; }
    else if (n === 'nogo'){ counts.nogo += 1; }
    else                  { counts.unknown += 1; }
  });
  for (const [k, v] of Object.entries(counts)) {
    const el = document.getElementById('dec-cnt-' + k);
    if (el) el.textContent = `(${v})`;
  }
}
"""

V4_CSS = """/* === P4 v4: 점수화 대기 배지 + 신청 상태 === */
.pdf-pending-chip { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; margin-left: 4px; vertical-align: middle; background: #f0f0f0; color: #666; cursor: help; }
.pdf-pending-chip::before { content: "🕒 "; }
.sb-pending-stats { font-size: 11px; color: #ad6800; padding-left: 8px; border-left: 1px solid #d9d9d9; margin-left: 8px; font-weight: 600; cursor: help; }
.sb-pending-stats.has-pending { color: #d4380d; animation: pulse-bell 2s ease-in-out infinite; }
@keyframes pulse-bell { 0%, 100% { opacity: 1; } 50% { opacity: 0.55; } }

/* 신청 상태 */
.status-toggle { display: inline-flex; gap: 2px; margin-left: 6px; vertical-align: middle; }
.status-btn { padding: 2px 7px; border: 1px solid #e0dcd7; background: white; border-radius: 10px; cursor: pointer; font-size: 10.5px; line-height: 1.2; }
.status-btn:hover { background: #fafafa; }
.status-btn.active { border-color: transparent; font-weight: 700; }
.status-btn.active.s-wip       { background: #fff7e6; color: #d46b08; border-color: #ffd591; }
.status-btn.active.s-submitted { background: #f6ffed; color: #389e0d; border-color: #b7eb8f; }
.status-btn.active.s-paused    { background: #f0f5ff; color: #1d39c4; border-color: #adc6ff; }
.status-btn.active.s-pass      { background: #fafafa; color: #999; border-color: #d9d9d9; text-decoration: line-through; }
.item.has-status-pass { opacity: 0.55; }
.item.has-status-submitted { box-shadow: inset 4px 0 0 #52c41a; }
.item.has-status-wip { box-shadow: inset 4px 0 0 #fa8c16; }
"""

V4_JS = """// === P4 v4: 점수화 대기 배지 + 신청 상태 ===
const STATUS_KEY = 'sinhon_kstartup_status';
const STATUSES = [
  { code: 'wip',       label: '📝 작성중',  cls: 's-wip' },
  { code: 'submitted', label: '📤 신청완료', cls: 's-submitted' },
  { code: 'paused',    label: '⏸ 보류',    cls: 's-paused' },
  { code: 'pass',      label: '❌ 패스',    cls: 's-pass' },
];
function getStatus() {
  try { return JSON.parse(localStorage.getItem(STATUS_KEY) || '{}'); } catch { return {}; }
}
function saveStatus(map) { localStorage.setItem(STATUS_KEY, JSON.stringify(map)); }
function setItemStatus(itemId, code) {
  const m = getStatus();
  if (m[itemId] === code) delete m[itemId]; else m[itemId] = code;
  saveStatus(m);
  applyStatusVisual(itemId);
  updatePendingStats();
}
function applyStatusVisual(itemId) {
  const m = getStatus();
  const code = m[itemId];
  let card;
  try { card = document.querySelector(`.item[data-id="${CSS.escape(itemId)}"]`); } catch { return; }
  if (!card) return;
  ['has-status-wip','has-status-submitted','has-status-paused','has-status-pass'].forEach(c => card.classList.remove(c));
  if (code) card.classList.add(`has-status-${code}`);
  card.querySelectorAll('.status-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.status === code);
  });
}
function loadStatusToggle(itemId) {
  let badges;
  try { badges = document.querySelector(`.item[data-id="${CSS.escape(itemId)}"] .badges`); } catch { return; }
  if (!badges || badges.querySelector('.status-toggle')) return;
  const wrap = document.createElement('span');
  wrap.className = 'status-toggle';
  wrap.innerHTML = STATUSES.map(s =>
    `<button class="status-btn ${s.cls}" data-status="${s.code}" onclick="setItemStatus('${itemId.replace(/'/g,"\\'")}','${s.code}')" title="${s.label}">${s.label}</button>`
  ).join('');
  badges.appendChild(wrap);
  applyStatusVisual(itemId);
}

// 점수화 대기 배지
async function loadPendingBadge(itemId) {
  const data = await loadAnalysis(itemId);
  const v = (data && data.verdict) || {};
  if (typeof v.pdf_pass_rate === 'number') return; // 점수화됨
  let badges;
  try { badges = document.querySelector(`.item[data-id="${CSS.escape(itemId)}"] .badges`); } catch { return; }
  if (!badges || badges.querySelector('.pdf-pending-chip')) return;
  const span = document.createElement('span');
  span.className = 'pdf-pending-chip';
  span.textContent = 'PDF 점수화 대기';
  span.title = 'Cowork 세션에서 점수화 필요. "오늘 큐 점수화" 한 줄 입력하면 자동 처리.';
  badges.appendChild(span);
}

async function updatePendingStats() {
  let pending = 0, scored = 0;
  await Promise.all(ITEMS.map(async (it) => {
    const data = await loadAnalysis(it.id);
    if (typeof data?.verdict?.pdf_pass_rate === 'number') scored += 1; else pending += 1;
  }));
  const el = document.getElementById('pending-stats');
  if (el) {
    el.innerHTML = pending > 0
      ? `🕒 점수화 대기 <b>${pending}</b>건 — Cowork 세션에서 처리 필요`
      : `✅ 모든 공고 점수화 완료 (${scored}건)`;
    el.classList.toggle('has-pending', pending > 0);
  }
}
"""

V3_CSS = """/* === P4 v3: 합격률 칩 + PDF 블록 최상단 === */
.pdf-pass-chip { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 700; margin-left: 4px; vertical-align: middle; font-family: 'SF Mono', Menlo, monospace; }
.pdf-pass-chip-high { background: #d9f7be; color: #389e0d; }
.pdf-pass-chip-mid  { background: #fff1b8; color: #ad6800; }
.pdf-pass-chip-low  { background: #ffd6e7; color: #c41d7f; }
"""
V3_JS = """// === P4 v3: 합격률 칩 ===
async function loadPdfPassChip(itemId) {
  const data = await loadAnalysis(itemId);
  const v = (data && data.verdict) || {};
  const p = v.pdf_pass_rate;
  if (typeof p !== 'number') return;
  let badges;
  try { badges = document.querySelector(`.item[data-id="${CSS.escape(itemId)}"] .badges`); } catch(_) { return; }
  if (!badges || badges.querySelector('.pdf-pass-chip')) return;
  const cls = p >= 0.5 ? 'pdf-pass-chip-high' : p >= 0.2 ? 'pdf-pass-chip-mid' : 'pdf-pass-chip-low';
  const span = document.createElement('span');
  span.className = `pdf-pass-chip ${cls}`;
  span.textContent = `합격 ${(p*100).toFixed(0)}%`;
  span.title = v.one_liner_pdf || '';
  badges.appendChild(span);
}
"""

def apply_v6(html: str, log: list[str]) -> str:
    """v6 증분: 신규 공고 NEW 배지 + sort-bar 카운트."""
    if SENTINEL_V6 in html:
        return html
    # CSS
    if "\n</style>" in html:
        html = html.replace("\n</style>", "\n" + V6_CSS + "</style>", 1)
        log.append("v6 CSS 주입 OK")
    # JS 헬퍼
    anc = "\nasync function render() {"
    if anc in html and V6_JS not in html:
        html = html.replace(anc, "\n" + V6_JS + anc, 1)
        log.append("v6 JS 헬퍼 주입 OK")
    # render() fan-out 에 loadNewBadge 추가
    old = "filtered.forEach(it => { loadTierRevisedBadge(it.id); loadPdfPassChip(it.id); loadPendingBadge(it.id); loadStatusToggle(it.id); });"
    new = "filtered.forEach(it => { loadTierRevisedBadge(it.id); loadPdfPassChip(it.id); loadPendingBadge(it.id); loadStatusToggle(it.id); loadNewBadge(it.id); });"
    if old in html:
        html = html.replace(old, new, 1)
        log.append("render() v6 fan-out 주입 OK")
    # sort-bar new-stats 슬롯
    old_bar = '<span class="sb-pending-stats" id="pending-stats">점수화 상태 확인 중…</span>'
    new_bar = '<span class="sb-pending-stats" id="pending-stats">점수화 상태 확인 중…</span><span class="sb-new-stats" id="new-stats"></span>'
    if old_bar in html:
        html = html.replace(old_bar, new_bar, 1)
        log.append("sortBar v6 신규 슬롯 OK")
    # 부트스트랩에 updateNewStats 호출
    old_boot = 'setTimeout(() => updateDecisionCounts(), 100);'
    new_boot = 'setTimeout(() => { updateDecisionCounts(); updateNewStats(); }, 100);'
    if old_boot in html:
        html = html.replace(old_boot, new_boot, 1)
        log.append("부트스트랩 updateNewStats 추가 OK")
    return html


def apply_v5(html: str, log: list[str]) -> str:
    """v5 증분: GO/조건부/NO-GO 결정 필터."""
    if SENTINEL_V5 in html:
        return html
    # CSS
    if "\n</style>" in html:
        html = html.replace("\n</style>", "\n" + V5_CSS + "</style>", 1)
        log.append("v5 CSS 주입 OK")
    # JS 헬퍼
    anc = "\nasync function render() {"
    if anc in html and V5_JS not in html:
        html = html.replace(anc, "\n" + V5_JS + anc, 1)
        log.append("v5 JS 헬퍼 주입 OK")
    # render() filter 안에 decision 필터 추가 — 마지막 fav 필터 다음에 끼움
    fav_anchor = 'if (state.fav === "only" && !_currentFavs.has(it.id)) return false;'
    fav_replacement = (
        'if (state.fav === "only" && !_currentFavs.has(it.id)) return false;\n'
        '    if (state.decision && state.decision !== "all") {\n'
        '      const _v = AA_CACHE.get(it.id)?.verdict;\n'
        '      if (!matchDecision(_v, state.decision)) return false;\n'
        '    }'
    )
    if fav_anchor in html and 'matchDecision' not in html.split(fav_anchor)[1].split('\n', 5)[1]:
        html = html.replace(fav_anchor, fav_replacement, 1)
        log.append("render() filter 에 decision 추가 OK")
    # render() 시작점에서 prefetch — _currentFavs 다음 줄에 await
    pref_anchor = '_currentFavs = getFavs();'
    pref_replacement = (
        '_currentFavs = getFavs();\n'
        '  if (state.decision && state.decision !== "all") { await ensureAnalysisReady(); }'
    )
    if pref_anchor in html and 'ensureAnalysisReady' not in html.split(pref_anchor)[1].split('\n', 5)[1]:
        html = html.replace(pref_anchor, pref_replacement, 1)
        log.append("render() prefetch 가드 OK")
    # 부트스트랩에 renderDecisionFilter + updateDecisionCounts 호출 추가
    boot_anchor = 'loadWeights().then(() => { renderSortBar(); render(); });'
    boot_replacement = (
        'loadWeights().then(() => { renderSortBar(); renderDecisionFilter(); render(); '
        'setTimeout(() => updateDecisionCounts(), 100); });'
    )
    if boot_anchor in html:
        html = html.replace(boot_anchor, boot_replacement, 1)
        log.append("부트스트랩에 결정 필터 초기화 추가 OK")
    return html


def apply_v4(html: str, log: list[str]) -> str:
    """v4 증분: 점수화 대기 배지·신청 상태 트래킹·sort-bar 카운트."""
    if SENTINEL_V4 in html:
        return html
    # CSS
    if "\n</style>" in html:
        html = html.replace("\n</style>", "\n" + V4_CSS + "</style>", 1)
        log.append("v4 CSS 주입 OK")
    # JS 헬퍼
    anc = "\nasync function render() {"
    if anc in html and V4_JS not in html:
        html = html.replace(anc, "\n" + V4_JS + anc, 1)
        log.append("v4 JS 헬퍼 주입 OK")
    # render() fan-out 에 loadPendingBadge + loadStatusToggle 추가, updatePendingStats 호출
    old = "filtered.forEach(it => { loadTierRevisedBadge(it.id); loadPdfPassChip(it.id); });"
    new = "filtered.forEach(it => { loadTierRevisedBadge(it.id); loadPdfPassChip(it.id); loadPendingBadge(it.id); loadStatusToggle(it.id); });\n  updatePendingStats();"
    if old in html:
        html = html.replace(old, new, 1)
        log.append("render() v4 fan-out 주입 OK")
    # sort-bar 에 점수화 대기 stats 슬롯
    old_bar = '<span class="sb-revised-stats" id="tier-revised-stats">tier 변동 집계 중…</span>'
    new_bar = '<span class="sb-revised-stats" id="tier-revised-stats">tier 변동 집계 중…</span><span class="sb-pending-stats" id="pending-stats">점수화 상태 확인 중…</span>'
    if old_bar in html:
        html = html.replace(old_bar, new_bar, 1)
        log.append("sortBar v4 점수화 대기 슬롯 OK")
    return html


def apply_v3(html: str, log: list[str]) -> str:
    """v3 증분: CSS 칩, JS 합격률 칩 fan-out, renderAnalysis return 순서 (pdf 맨 앞)."""
    if SENTINEL_V3 in html:
        return html
    # CSS
    if "\n</style>" in html:
        html = html.replace("\n</style>", "\n" + V3_CSS + "</style>", 1)
        log.append("v3 CSS 주입 OK")
    # JS 헬퍼 — async function render() 직전에 삽입
    anc = "\nasync function render() {"
    if anc in html and V3_JS not in html:
        html = html.replace(anc, "\n" + V3_JS + anc, 1)
        log.append("v3 JS 헬퍼 주입 OK")
    # render() fan-out 에 loadPdfPassChip 추가
    old = "filtered.forEach(it => loadTierRevisedBadge(it.id));"
    new = "filtered.forEach(it => { loadTierRevisedBadge(it.id); loadPdfPassChip(it.id); });"
    if old in html:
        html = html.replace(old, new, 1)
        log.append("render() 합격률 칩 fan-out 주입 OK")
    # renderAnalysis return 순서: pdfBlockHtml 을 맨 앞으로
    old_ret = "return natureHtml + fitHtml + roiHtml + decHtml + altHtml + pdfBlockHtml + metaHtml;"
    new_ret = "return pdfBlockHtml + natureHtml + fitHtml + roiHtml + decHtml + altHtml + metaHtml;"
    if old_ret in html:
        html = html.replace(old_ret, new_ret, 1)
        log.append("renderAnalysis return 순서 변경 OK (PDF 블록 → 맨 앞)")
    return html


def patch(html: str) -> tuple[str, list[str]]:
    log: list[str] = []
    if SENTINEL_V6 in html:
        log.append("이미 v6 패치됨 — skip")
        return html, log
    if SENTINEL_V5 in html and SENTINEL_V6 not in html:
        log.append("v5 패치 감지 → v6 증분 적용")
        return apply_v6(html, log), log
    if SENTINEL in html and SENTINEL_V2 in html and SENTINEL_V3 in html and SENTINEL_V4 in html and SENTINEL_V5 not in html:
        log.append("v4 패치 감지 → v5+v6 증분 적용")
        html = apply_v5(html, log)
        return apply_v6(html, log), log
    if SENTINEL in html and SENTINEL_V2 in html and SENTINEL_V3 in html and SENTINEL_V4 not in html:
        log.append("v3 패치 감지 → v4+v5+v6 증분 적용")
        html = apply_v4(html, log)
        html = apply_v5(html, log)
        return apply_v6(html, log), log
    if SENTINEL in html and SENTINEL_V2 in html and SENTINEL_V3 not in html:
        log.append("v2 패치 감지 → v3+v4+v5+v6 증분 적용")
        html = apply_v3(html, log)
        html = apply_v4(html, log)
        html = apply_v5(html, log)
        return apply_v6(html, log), log
    if SENTINEL in html and SENTINEL_V2 not in html:
        log.append("v1 패치 감지 → v2 증분 적용 (CSS·JS 추가만)")
        # v1만 있는 경우: tier_revised 관련 코드만 끼워넣음
        # CSS 보강
        css_patch = """/* P4 v2: tier_revised badge */
.tier-revised-badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 10.5px; font-weight: 700; margin-left: 4px; vertical-align: middle; }
.tier-revised-up   { background: #d9f7be; color: #389e0d; }
.tier-revised-down { background: #fff1f0; color: #cf1322; }
.tier-revised-same { background: #f0f5ff; color: #1d39c4; }
.tier-revised-up::before   { content: "🔼"; margin-right: 3px; }
.tier-revised-down::before { content: "🔽"; margin-right: 3px; }
.tier-revised-same::before { content: "✓";  margin-right: 3px; }
.sb-revised-stats { font-size: 11px; color: #722ed1; padding-left: 8px; border-left: 1px solid #d9d9d9; margin-left: 8px; }
"""
        if SENTINEL_V2 not in html and "\n</style>" in html:
            html = html.replace("\n</style>", "\n" + SENTINEL_V2 + "\n" + css_patch + "</style>", 1)
            log.append("v2 CSS 주입 OK")
        # JS 헬퍼 보강
        js_patch_v2 = """// === P4 v2: tier_revised ===
const TIER_RANK = { red: 0, orange: 1, yellow: 2, green: 3 };
async function loadTierRevisedBadge(itemId) {
  const data = await loadAnalysis(itemId);
  const v = (data && data.verdict) || {};
  const rev = v.tier_revised;
  if (!rev) return;
  let badges;
  try { badges = document.querySelector(`.item[data-id="${CSS.escape(itemId)}"] .badges`); } catch (_) { return; }
  if (!badges || badges.querySelector('.tier-revised-badge')) return;
  const item = ITEMS.find(i => i.id === itemId);
  const cur = item?.tier;
  const cls = TIER_RANK[rev] > TIER_RANK[cur] ? 'tier-revised-up'
            : TIER_RANK[rev] < TIER_RANK[cur] ? 'tier-revised-down' : 'tier-revised-same';
  const label = TIER_RANK[rev] === TIER_RANK[cur] ? `PDF: ${rev}` : `${cur}→${rev}`;
  const span = document.createElement('span');
  span.className = `tier-revised-badge ${cls}`;
  span.textContent = label;
  span.title = v.tier_revised_reason || '';
  badges.appendChild(span);
}
async function updateTierRevisedStats() {
  const stats = { up: 0, down: 0, same: 0, none: 0 };
  await Promise.all(ITEMS.map(async (it) => {
    const data = await loadAnalysis(it.id);
    const rev = data?.verdict?.tier_revised;
    if (!rev) { stats.none += 1; return; }
    const d = TIER_RANK[rev] - TIER_RANK[it.tier];
    if (d > 0) stats.up += 1;
    else if (d < 0) stats.down += 1;
    else stats.same += 1;
  }));
  const el = document.getElementById('tier-revised-stats');
  if (el) el.innerHTML = `tier 변동: 🔼 ${stats.up} · 🔽 ${stats.down} · ✓ ${stats.same} (PDF 미평가 ${stats.none})`;
}
"""
        anchor = "\nasync function render() {"
        if anchor in html:
            html = html.replace(anchor, "\n" + js_patch_v2 + "\nasync function render() {", 1)
            log.append("v2 JS 헬퍼 주입 OK")
        # render() 끝부분 확장: tier_revised fan-out
        old = 'container.innerHTML = (await sortItems(filtered)).map(renderCard).join("")'
        new = 'container.innerHTML = (await sortItems(filtered)).map(renderCard).join("");\n  filtered.forEach(it => loadTierRevisedBadge(it.id));\n  updateTierRevisedStats();\n  // v2 patched (was single line)'
        if old in html and "loadTierRevisedBadge" not in html.split(old)[1].split('\n', 5)[1]:
            html = html.replace(old, new, 1)
            log.append("render() v2 fan-out 주입 OK")
        # 카드 data-id 속성
        if 'data-id="${escapeHtml(it.id)}"' not in html:
            anchor2 = '<div class="item tier-${it.tier}${it.annual_recurring ? \' annual\' : \'\'}"\n       data-source='
            if anchor2 in html:
                html = html.replace(
                    anchor2,
                    '<div class="item tier-${it.tier}${it.annual_recurring ? \' annual\' : \'\'}"\n       data-id="${escapeHtml(it.id)}" data-source='
                )
                log.append("카드 data-id 속성 주입 OK")
        # sortBar 에 stats 슬롯 추가
        old_bar = "if (bar) bar.innerHTML = `<span class=\"sb-h\">정렬</span>${pills}<span class=\"sb-edit\">"
        new_bar = "if (bar) bar.innerHTML = `<span class=\"sb-h\">정렬</span>${pills}<span class=\"sb-revised-stats\" id=\"tier-revised-stats\">tier 변동 집계 중…</span><span class=\"sb-edit\">"
        if old_bar in html:
            html = html.replace(old_bar, new_bar, 1)
            log.append("sortBar v2 stats 슬롯 OK")
        # v2 적용 후 v3, v4, v5, v6 도 같이
        html = apply_v3(html, log)
        html = apply_v4(html, log)
        html = apply_v5(html, log)
        return apply_v6(html, log), log

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

    # filtered.map → (await sortItems(filtered)).map + tier_revised badge fan-out
    target_render = 'container.innerHTML = filtered.map(renderCard).join("")'
    if target_render in html:
        html = html.replace(
            target_render,
            'container.innerHTML = (await sortItems(filtered)).map(renderCard).join("");\n  filtered.forEach(it => loadTierRevisedBadge(it.id));\n  updateTierRevisedStats();\n  // (was: container.innerHTML = filtered.map(renderCard).join(""))'
        )
        log.append("render() 정렬 호출 + tier_revised fan-out 주입 OK")
    else:
        log.append("⚠ filtered.map 호출 패턴 못 찾음")

    # 카드 div 에 data-id 속성 추가 (tier_revised 배지 위치 식별용)
    if 'data-id="${escapeHtml(it.id)}"' not in html:
        anchor = '<div class="item tier-${it.tier}${it.annual_recurring ? \' annual\' : \'\'}"\n       data-source='
        if anchor in html:
            html = html.replace(
                anchor,
                '<div class="item tier-${it.tier}${it.annual_recurring ? \' annual\' : \'\'}"\n       data-id="${escapeHtml(it.id)}" data-source='
            )
            log.append("카드 data-id 속성 주입 OK")
        else:
            log.append("⚠ 카드 div anchor 못 찾음 — tier_revised 배지 미작동 가능")

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

    # fresh 패치 흐름 마지막에 v3~v6 도 같이
    html = apply_v3(html, log)
    html = apply_v4(html, log)
    html = apply_v5(html, log)
    return apply_v6(html, log), log


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
