#!/usr/bin/env python3
"""
K-Startup 공고 자동 업데이트 오케스트레이터 v4 (founder-gov-radar)
RSS 크롤 → 규칙 분류(+evidence) → 만료 삭제 → upsert → Haiku deep_summary 생성 → 저장

v4 변경점:
- classify() v7: (tier, evidence_dict) 반환. note = evidence.summary_reason
- item.classify_evidence 저장 (rule_checks / risk_flags / category_hints)
- master_modules.json 동적 주입 — 공고 카테고리에 맞는 모듈 2~5개만 Haiku에 전달
- deep_summary 새 스키마: fit / strategy[] / checkpoints[] / difficulty / next_action
                         + master_anchor / evidence_quote / risk_notes[]
- --force-regenerate: pool 전체 deep_summary 재생성 (1회성 백필)
- 🔴 공고는 pool 제외 유지 (기존 로직)

Usage:
  python update.py                  # 일반 실행 (신규 최대 10건 요약)
  python update.py --force-regenerate  # 전체 재생성 (pool 전체 재요약)
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from crawl import crawl
from classify import classify, TODAY

KST = timezone(timedelta(hours=9))
POOL_FILE = "recommendations.json"
MASTER_MODULES_FILE = "master_modules.json"
STALE_DAYS = 14
HISTORY_MAX_DAYS = 30

# ── Haiku deep_summary 설정 ──
HAIKU_MODEL = "claude-haiku-4-5-20251001"
HAIKU_MAX_NEW_PER_RUN = 400           # 일반 실행: 상세 가이드 전체 백필용 1회성 상향 (원복 예정)
HAIKU_MAX_BACKFILL_PER_RUN = 150      # --force-regenerate: 최대 150건
HAIKU_TIMEOUT_S = 60
HAIKU_MAX_TOKENS = 1400               # v7.2: 900→1400 — JSON 잘림 방지

BASE_SYSTEM_PREFIX = """당신은 허파랑 대표(법인 XCom)의 정부지원사업 컨설턴트입니다.
sinhon.life(B2C 신혼부부 라이프스타일 플랫폼)의 정체성·당사자성·플라이휠을 숙지한 상태로,
아래 공고가 이 사업에 왜/어떻게 맞는지 마스터팩 근거에 기반해 답합니다.

---
[마스터팩 모듈] (공고 유형별로 동적 주입됨)

{MODULES}

---
"""

SCHEMA_INSTRUCTION = """다음 JSON 스키마에 정확히 맞춰 응답하세요.
반드시 `{` 로 시작하고 `}` 로 끝나는 순수 JSON만 출력하세요. 코드펜스(```), 설명 문장, 전후 공백 절대 금지.

{
  "fit": "왜 sinhon.life에 맞는지 2~3문장. 공고 특징 + 마스터팩 어떤 포인트(§N 또는 모듈명)와 어떻게 연결되는지 구체적으로 명시",
  "strategy": ["지원 포지셔닝 액션 1 (플라이휠/당사자성 연결, 구체적)", "액션 2", "액션 3"],
  "checkpoints": ["지원 전 확인 필수사항 1 (자격·서류·지역·업력 등)", "확인사항 2", "확인사항 3"],
  "difficulty": "low|medium|high",
  "next_action": "오늘~이번주 안에 해야 할 가장 첫 실행 액션 1개 (20자 이내)",
  "master_anchor": "가장 강하게 당긴 마스터팩 앵커 (예: '00_MASTER §3-5' 또는 'M05_ai_tech')",
  "evidence_quote": "공고 원문에서 따온 핵심 근거 1구절 (30자 이내, 없으면 빈 문자열)",
  "risk_notes": ["이 공고 지원 시 주의점 1", "주의점 2"]
}"""


def load_master_modules() -> dict:
    """마스터팩 모듈 매니페스트 로드"""
    try:
        with open(MASTER_MODULES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[modules] {MASTER_MODULES_FILE} 로드 실패: {e}. 기본 컨텍스트만 사용", file=sys.stderr)
        return {
            "always_inject": [],
            "modules": {},
        }


def select_modules(item: dict, evidence: dict, manifest: dict) -> list:
    """
    공고의 category_hints + tier + note 키워드를 보고 주입할 모듈 선택.
    반환: [(module_id, module_dict), ...]
    """
    modules = manifest.get("modules", {})
    if not modules:
        return []

    always_keys = manifest.get("always_inject", [])
    selected_ids = list(always_keys)  # M01_identity, M02_spine은 항상

    hints = set(evidence.get("category_hints", []))
    title = (item.get("title", "") + " " + item.get("note", "")).lower()

    # hint 기반 모듈 선택
    hint_to_module = {
        "ai": "M05_ai_tech",
        "content": "M06_content_engine",
        "incheon": "M07_incheon",
        "global": "M09_global",
        "social": "M08_events",
        "budget": "M10_team_budget",
    }
    for hint, mod_id in hint_to_module.items():
        if hint in hints and mod_id not in selected_ids:
            selected_ids.append(mod_id)

    # tier가 green/orange이면 플라이휠 · 문제인식 항상 추가 (핵심 공고)
    if item.get("tier") in ("green", "orange"):
        for mod_id in ("M03_flywheel", "M04_problem"):
            if mod_id not in selected_ids:
                selected_ids.append(mod_id)
    # yellow라도 "사업화", "BM", "수익모델" 키워드 있으면 플라이휠 추가
    elif any(k in title for k in ("사업화", "BM", "수익모델", "수익 모델", "플랫폼")):
        if "M03_flywheel" not in selected_ids:
            selected_ids.append("M03_flywheel")

    # 5개 초과면 앞에서 5개만 (토큰 예산)
    selected_ids = selected_ids[:5]

    return [(mid, modules[mid]) for mid in selected_ids if mid in modules]


def format_modules_block(selected: list) -> str:
    """선택된 모듈들을 system 프롬프트에 삽입할 텍스트로 포맷"""
    if not selected:
        return "(마스터팩 로드 실패 — 기본 컨텍스트만 사용)"
    blocks = []
    for mid, mod in selected:
        blocks.append(
            f"### {mid}: {mod['name']} (anchor: {mod.get('anchor', '')})\n"
            f"{mod['summary']}"
        )
    return "\n\n".join(blocks)


def load_pool() -> dict:
    try:
        with open(POOL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("schema_version") not in (2, 3, 4):
            raise ValueError("schema mismatch")
        # v2/v3 → v4 마이그레이션
        data["schema_version"] = 4
        data.setdefault("history", [])
        return data
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {
            "schema_version": 4,
            "last_updated": TODAY,
            "updated_at_kst": "",
            "history": [],
            "items": [],
            "red_count_today": 0,
        }


def save_pool(pool: dict, now_kst: datetime):
    pool["last_updated"] = TODAY
    pool["updated_at_kst"] = now_kst.strftime("%Y-%m-%dT%H:%M:%S+09:00")
    with open(POOL_FILE, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)
    print(f"[save] {POOL_FILE} 저장 완료 ({len(pool['items'])}건)", file=sys.stderr)


def expire_items(items: list) -> tuple:
    stale_cutoff = (datetime.now(KST) - timedelta(days=STALE_DAYS)).strftime("%Y-%m-%d")
    kept, expired_titles = [], []
    for item in items:
        dl = item.get("deadline", "")
        ls = item.get("last_seen", "")
        if dl and dl < TODAY:
            expired_titles.append(item.get("title", ""))
        elif ls and ls < stale_cutoff:
            expired_titles.append(item.get("title", "") + " (stale)")
        else:
            kept.append(item)
    return kept, expired_titles


def prune_history(history: list, now_kst: datetime) -> list:
    cutoff = (now_kst - timedelta(days=HISTORY_MAX_DAYS)).strftime("%Y-%m-%d")
    return [h for h in history if h.get("date", "") >= cutoff]


# ── Haiku deep_summary 생성 ───────────────────────────────────
def _format_risk_flags(flags):
    """v7.2: risk_flags는 list[dict] 형식 ({type,severity,msg}). 표시용 문자열로 변환."""
    out = []
    for f in flags or []:
        if isinstance(f, dict):
            msg = f.get("msg") or f.get("type") or ""
            sev = f.get("severity", "")
            if sev:
                out.append(f"[{sev}] {msg}")
            else:
                out.append(msg)
        else:
            out.append(str(f))
    return out


def _parse_json_response(text: str):
    raw = (text or "").strip()
    candidates = [raw]

    stripped = raw
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped[3:]
        stripped = stripped.rstrip()
        if stripped.endswith("```"):
            stripped = stripped[:-3].rstrip()
        candidates.append(stripped)

    try:
        s = raw.index("{")
        e = raw.rindex("}") + 1
        candidates.append(raw[s:e])
    except ValueError:
        pass

    data = None
    for cand in candidates:
        try:
            data = json.loads(cand)
            break
        except Exception:
            continue
    if data is None:
        return None

    required = {"fit", "strategy", "checkpoints", "difficulty", "next_action"}
    if not required.issubset(data.keys()):
        return None
    if not isinstance(data.get("strategy"), list) or not isinstance(data.get("checkpoints"), list):
        return None
    diff = str(data.get("difficulty", "")).strip().lower()
    # easy/hard 동의어 허용 (Opus/Haiku 모델이 혼용)
    diff_map = {"easy": "low", "쉬움": "low", "낮음": "low",
                "medium": "medium", "보통": "medium", "중간": "medium",
                "hard": "high", "어려움": "high", "높음": "high",
                "low": "low", "high": "high"}
    data["difficulty"] = diff_map.get(diff, "medium")
    # v4 신규 필드는 선택적 — 없으면 기본값
    data.setdefault("master_anchor", "")
    data.setdefault("evidence_quote", "")
    if "risk_notes" not in data or not isinstance(data["risk_notes"], list):
        data["risk_notes"] = []
    return data


def generate_deep_summary(client, item: dict, evidence: dict, manifest: dict):
    selected = select_modules(item, evidence, manifest)
    modules_block = format_modules_block(selected)
    system_prompt = BASE_SYSTEM_PREFIX.replace("{MODULES}", modules_block) + "\n" + SCHEMA_INSTRUCTION

    structured = item.get("structured", {}) or {}
    user_msg = (
        f"[공고]\n"
        f"- 제목: {item.get('title', '')}\n"
        f"- 주관기관: {item.get('agency', '') or '(미상)'}\n"
        f"- 마감일: {item.get('deadline', '') or '(미확인)'}\n"
        f"- 티어: {item.get('tier', '')}\n"
        f"- 분류 요약: {item.get('note', '')}\n"
        f"- 지역: {structured.get('region', '')}\n"
        f"- 업종분류: {structured.get('biz_class', '')}\n"
        f"- 업력: {structured.get('biz_enyy', '')}\n"
        f"- 지원대상: {(structured.get('apply_target_desc', '') or '')[:300]}\n"
        f"- 카테고리 힌트: {', '.join(evidence.get('category_hints', []))}\n"
        f"- 주의신호: {', '.join(_format_risk_flags(evidence.get('risk_flags', [])))}\n\n"
        "JSON만 응답하세요. 백틱(```)으로 감싸지 마세요. 응답은 반드시 { 로 시작해서 } 로 끝나야 합니다."
    )
    try:
        resp = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=HAIKU_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
            timeout=HAIKU_TIMEOUT_S,
        )
        text = resp.content[0].text if resp.content else ""
        parsed = _parse_json_response(text)
        if parsed is None:
            print(f"[haiku] 파싱 실패: {item.get('pbancSn')} — {text[:80]}", file=sys.stderr)
            return None
        # 어떤 모듈이 주입됐는지 기록 (디버깅/투명성)
        parsed["_modules_used"] = [mid for mid, _ in selected]
        return parsed
    except Exception as e:
        print(f"[haiku] 호출 실패 ({item.get('pbancSn')}): {e}", file=sys.stderr)
        return None


def enrich_deep_summaries(items: list, manifest: dict, force_regenerate: bool = False):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("[haiku] ANTHROPIC_API_KEY 없음 — deep_summary 생성 스킵", file=sys.stderr)
        return (0, 0)

    if force_regenerate:
        targets = list(items)
        max_cap = HAIKU_MAX_BACKFILL_PER_RUN
        print(f"[haiku] --force-regenerate: pool 전체 {len(targets)}건 재생성 시도 (상한 {max_cap})", file=sys.stderr)
    else:
        targets = [it for it in items if not it.get("deep_summary") or it.get("deep_summary", {}).get("_schema") != "v4"]
        if not targets:
            print("[haiku] 모든 항목에 v4 deep_summary 존재 — 스킵", file=sys.stderr)
            return (0, 0)
        max_cap = HAIKU_MAX_NEW_PER_RUN

    tier_order = {"green": 0, "orange": 1, "yellow": 2, "red": 9}
    targets.sort(key=lambda x: tier_order.get(x.get("tier", "yellow"), 9))
    to_process = targets[:max_cap]

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
    except ImportError:
        print("[haiku] anthropic 패키지 없음 — deep_summary 생성 스킵", file=sys.stderr)
        return (0, 0)

    print(f"[haiku] deep_summary 생성 대상 {len(to_process)}건 (전체 타겟 {len(targets)}건)", file=sys.stderr)

    succ = 0
    for idx, item in enumerate(to_process, 1):
        evidence = item.get("classify_evidence") or {}
        ds = generate_deep_summary(client, item, evidence, manifest)
        if ds:
            ds["_schema"] = "v4"
            item["deep_summary"] = ds
            succ += 1
            print(f"[haiku] {idx}/{len(to_process)} OK {item.get('pbancSn')}: {item.get('title', '')[:30]}...", file=sys.stderr)
        else:
            print(f"[haiku] {idx}/{len(to_process)} FAIL {item.get('pbancSn')}", file=sys.stderr)
        time.sleep(0.3)

    return (succ, len(to_process))


# ── 메인 ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-regenerate", action="store_true",
                        help="pool 전체의 deep_summary를 강제 재생성 (1회성 백필)")
    parser.add_argument("--skip-crawl", action="store_true",
                        help="크롤을 스킵하고 pool 재분류 + Haiku만 돌림 (백필용)")
    args = parser.parse_args()

    now_kst = datetime.now(KST)
    manifest = load_master_modules()

    pool = load_pool()
    existing_items = pool.get("items", [])
    print(f"[load] 기존 풀: {len(existing_items)}건", file=sys.stderr)

    if args.skip_crawl:
        # 재분류 only: evidence 없으면 채우고, tier 재판정
        print("[skip-crawl] 크롤 스킵. pool 전체 재분류만 수행", file=sys.stderr)
        kept_items = []
        red_count = 0
        reclassified = 0
        for item in existing_items:
            prev_tier = item.get("tier")
            tier, evidence = classify(item)
            item["tier"] = tier
            item["note"] = evidence.get("summary_reason", "")
            item["classify_evidence"] = evidence
            if tier == "red":
                red_count += 1
                continue  # 🔴는 pool 제외
            if prev_tier != tier:
                reclassified += 1
            kept_items.append(item)
        print(f"[reclassify] 재분류 {reclassified}건 변경, 🔴 제외 {red_count}건", file=sys.stderr)

        expired_titles = []
        new_added = []
        updated_titles = []
        crawled = []
    else:
        kept_items, expired_titles = expire_items(existing_items)
        if expired_titles:
            print(f"[expire] {len(expired_titles)}건 삭제", file=sys.stderr)

        known_sns = {it["pbancSn"] for it in kept_items if it.get("pbancSn")}
        crawled = crawl(known_sns)

        kept_by_sn = {it["pbancSn"]: it for it in kept_items if it.get("pbancSn")}

        red_count = 0
        new_added = []
        updated_titles = []

        for crawled_item in crawled:
            sn = crawled_item["pbancSn"]
            tier, evidence = classify(crawled_item)
            reason = evidence.get("summary_reason", "")

            if tier == "red":
                red_count += 1
                if sn in kept_by_sn:
                    kept_items = [it for it in kept_items if it.get("pbancSn") != sn]
                continue

            if sn in kept_by_sn:
                existing = kept_by_sn[sn]
                existing["last_seen"] = TODAY
                changed = False
                new_deadline = crawled_item.get("deadline", "") or existing.get("deadline", "")
                new_title = crawled_item.get("title", "") or existing.get("title", "")
                new_agency = crawled_item.get("agency", "") or existing.get("agency", "")
                if existing.get("tier") != tier:
                    changed = True
                if existing.get("deadline", "") != new_deadline and new_deadline:
                    changed = True
                if existing.get("title", "") != new_title and new_title:
                    changed = True
                if existing.get("note", "") != reason:
                    changed = True
                if existing.get("agency", "") != new_agency and new_agency:
                    changed = True
                existing["tier"] = tier
                existing["note"] = reason
                existing["classify_evidence"] = evidence
                existing["deadline"] = new_deadline
                existing["title"] = new_title
                if new_agency:
                    existing["agency"] = new_agency
                if crawled_item.get("structured"):
                    existing["structured"] = crawled_item["structured"]
                if changed:
                    existing["last_changed_at"] = TODAY
                    updated_titles.append(existing.get("title", ""))
            else:
                new_item = {
                    "pbancSn": sn,
                    "title": crawled_item["title"],
                    "agency": crawled_item.get("agency", ""),
                    "deadline": crawled_item.get("deadline", ""),
                    "url": crawled_item.get("url", ""),
                    "tier": tier,
                    "note": reason,
                    "classify_evidence": evidence,
                    "first_seen": TODAY,
                    "last_seen": TODAY,
                    "structured": crawled_item.get("structured", {}),
                }
                kept_items.append(new_item)
                new_added.append(new_item["title"])

    tier_order = {"green": 0, "orange": 1, "yellow": 2}
    kept_items.sort(key=lambda x: (
        tier_order.get(x.get("tier", "yellow"), 9),
        x.get("deadline") or "9999-99-99",
    ))

    # deep_summary 생성 (캐시 or --force-regenerate)
    ds_succ, ds_attempt = enrich_deep_summaries(kept_items, manifest, force_regenerate=args.force_regenerate)

    # history 기록
    history = prune_history(pool.get("history", []), now_kst)
    history.append({
        "date": TODAY,
        "at_kst": now_kst.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "new": len(new_added),
        "updated": len(updated_titles),
        "expired": len(expired_titles),
        "total": len(kept_items),
        "red_excluded": red_count,
        "deep_summary_generated": ds_succ,
        "force_regenerate": args.force_regenerate,
    })
    seen = set()
    deduped = []
    for h in reversed(history):
        if h["date"] in seen:
            continue
        seen.add(h["date"])
        deduped.append(h)
    pool["history"] = list(reversed(deduped))

    pool["items"] = kept_items
    pool["red_count_today"] = red_count
    pool["_meta"] = {
        "expired": expired_titles,
        "new_added": new_added,
        "updated_today": updated_titles,
        "deep_summary": {"generated": ds_succ, "attempted": ds_attempt, "force_regenerate": args.force_regenerate},
        "stats": {
            "green": sum(1 for i in kept_items if i.get("tier") == "green"),
            "yellow": sum(1 for i in kept_items if i.get("tier") == "yellow"),
            "orange": sum(1 for i in kept_items if i.get("tier") == "orange"),
            "red_excluded": red_count,
            "expired_removed": len(expired_titles),
            "total_pool": len(kept_items),
            "rss_total": len(crawled) if not args.skip_crawl else 0,
        },
    }
    save_pool(pool, now_kst)

    stats = pool["_meta"]["stats"]
    print(f"\n{'='*50}", file=sys.stderr)
    print(f"[결과] nidview {stats['rss_total']} → 🟢{stats['green']} 🟡{stats['yellow']} 🟠{stats['orange']} 🔴{stats['red_excluded']} | "
          f"신규 {len(new_added)} · 수정 {len(updated_titles)} · 만료 {stats['expired_removed']} · 풀 {stats['total_pool']} · "
          f"Haiku {ds_succ}/{ds_attempt}건", file=sys.stderr)


if __name__ == "__main__":
    main()
