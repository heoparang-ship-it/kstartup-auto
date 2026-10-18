#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import compileall
import importlib
import json
import py_compile
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY_ROOTS = [REPO, REPO / "sources", REPO / "tools", REPO / "tests"]
CLASSIFY_NAMES = {"classify", "classify_itp", "_classify_external"}
DOCUMENTED_MISSING = (
    "crawl_all.py",
    "classify_v10.py",
    "normalize.py",
    "crawl_v6.py",
)
WATER_TAGS = (
    "창업,서울,부산,대구,인천,전남광주,대전,울산,세종,경기,"
    "강원,충북,충남,전북,경북,경남,제주"
)


def iter_py() -> list[Path]:
    files: list[Path] = []
    for root in PY_ROOTS:
        if not root.exists():
            continue
        for p in root.glob("*.py"):
            if p.name.startswith("."):
                continue
            files.append(p)
    return sorted(files)


def compile_tree() -> list[str]:
    errors: list[str] = []
    ok = compileall.compile_dir(str(REPO), quiet=1, maxlevels=1, rx=re.compile(r"/\."))
    if not ok:
        errors.append("compileall reported a failure")
    for p in iter_py():
        try:
            py_compile.compile(str(p), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(str(exc))
    return errors


def import_core() -> list[str]:
    errors: list[str] = []
    sys.path.insert(0, str(REPO))
    for mod in ("classify", "crawl", "sources._base"):
        try:
            importlib.import_module(mod)
        except Exception as exc:
            errors.append(f"import {mod} failed: {type(exc).__name__}: {exc}")
    return errors


def classify_entrypoints() -> list[str]:
    found: list[str] = []
    for p in iter_py():
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in CLASSIFY_NAMES:
                found.append(f"{p.relative_to(REPO)}:{node.name}")
    return found


def documented_missing() -> list[str]:
    return [name for name in DOCUMENTED_MISSING if not (REPO / name).exists()]


def pool_missing_source() -> tuple[int, int]:
    pool_path = REPO / "recommendations.json"
    data = json.loads(pool_path.read_text(encoding="utf-8"))
    items = data.get("items") or []
    missing = sum(1 for it in items if not it.get("source"))
    return missing, len(items)


def dashboard_baked_count() -> int | None:
    html = (REPO / "index.html").read_text(encoding="utf-8")
    match = re.search(r"const ITEMS = (\[.*?\]);", html)
    if not match:
        return None
    return len(json.loads(match.group(1)))


def classify_version() -> str:
    sys.path.insert(0, str(REPO))
    from classify import CLASSIFY_VERSION

    return CLASSIFY_VERSION


def profile_claims_v92() -> bool:
    text = (REPO / "profile.md").read_text(encoding="utf-8")
    return "classify.py **v9.2**" in text or "classify.py v9.2" in text


def parse_broken_fixture() -> str | None:
    fixture = REPO / "tests" / "fixtures" / "fstring_unescaped.txt"
    if not fixture.exists():
        return "missing tests/fixtures/fstring_unescaped.txt"
    try:
        ast.parse(fixture.read_text(encoding="utf-8"))
    except SyntaxError:
        return None
    return "fixture compiled, so it no longer reproduces 1bf05f4"


def load_pool_resets_on_error() -> bool:
    text = (REPO / "update.py").read_text(encoding="utf-8")
    return "except (FileNotFoundError, json.JSONDecodeError, ValueError)" in text


def hashtag_makes_incheon() -> str | None:
    bizinfo = REPO / "sources" / "bizinfo.py"
    src = bizinfo.read_text(encoding="utf-8")
    if "_extract_region(raw.get(\"hashtags\"" not in src:
        return None
    sys.path.insert(0, str(REPO))
    from sources.bizinfo import BizinfoSource

    region = BizinfoSource._extract_region(WATER_TAGS)
    if region and "인천" in region:
        return region
    return None


def run_gate() -> int:
    errors = compile_tree() + import_core()
    for err in errors:
        print(f"FAIL {err}", file=sys.stderr)
    if errors:
        return 1
    print("PASS gate: python compiles and core modules import")
    return 0


def run_debt() -> int:
    failures: list[str] = []
    entries = classify_entrypoints()
    print(f"classify_entrypoints={entries}")
    if len(entries) != 1:
        failures.append(
            f"expected one classify entry point, found {len(entries)}: {entries}"
        )
    missing = documented_missing()
    print(f"documented_missing={missing}")
    if missing:
        failures.append(f"documented modules missing: {missing}")
    n_miss, n_items = pool_missing_source()
    print(f"pool_missing_source={n_miss}/{n_items}")
    if n_miss:
        failures.append(f"{n_miss} pool items have no source field")
    baked = dashboard_baked_count()
    print(f"dashboard_ITEMS={baked} pool_items={n_items}")
    if baked is not None and baked != n_items:
        failures.append(
            f"index.html ITEMS has {baked} rows, recommendations.json has {n_items}"
        )
    version = classify_version()
    print(f"CLASSIFY_VERSION={version} profile_claims_v92={profile_claims_v92()}")
    if profile_claims_v92() and version != "v9.2":
        failures.append(
            f"profile.md claims classify v9.2, classify.py stamps {version}"
        )
    fixture_err = parse_broken_fixture()
    if fixture_err:
        failures.append(fixture_err)
    else:
        print("PASS fixture: fstring_unescaped.txt still SyntaxError (1bf05f4)")
    if load_pool_resets_on_error():
        failures.append(
            "load_pool returns an empty pool on schema mismatch or bad JSON"
        )
        print("load_pool_resets_on_error=True")
    region = hashtag_makes_incheon()
    print(f"hashtag_region={region}")
    if region is not None:
        failures.append(
            f"BizinfoSource._extract_region treats nationwide hashtags as Incheon ({region})"
        )
    for err in failures:
        print(f"DEBT {err}", file=sys.stderr)
    if failures:
        print(f"FAIL debt: {len(failures)} invariant(s)")
        return 1
    print("PASS debt")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=("gate", "debt", "both"),
        default="gate",
    )
    args = parser.parse_args()
    status = 0
    if args.phase in ("gate", "both"):
        status = run_gate() or status
    if args.phase in ("debt", "both"):
        debt = run_debt()
        if args.phase == "debt":
            return debt
        if debt:
            print("debt is informational until PR-3 and PR-2 land")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
