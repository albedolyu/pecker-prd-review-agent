"""doc_coherence.py — 校验文档和代码行为的一致性。

为什么做: 项目有过多次自评文档漂移历史(HARNESS_MATURITY / PRODUCTION_READINESS /
CHANGELOG / 产品介绍),人工维护成本高且总是滞后。这里用 grep + AST 最朴素的方式做
3 类机器可查的一致性:

  1. endpoints: README/docs/*.md 里提到的 /api/... 都必须在 FastAPI 路由里
  2. env_vars:  .env.example 列的环境变量集合 vs 代码 os.environ[...] 实际读的集合
                差集即为漂移(例:代码新加了 PECKER_FOO 但 .env.example 忘了)
  3. file_paths: 文档 markdown 里 backtick 包裹的相对路径(*.py/*.ts/*.tsx/*.yml/
                 *.yaml/*.json)必须真实存在

设计边界:
- 只扫 repo 根的 *.md 和 docs/(不含 docs/archive/)、workspace-sample/wiki/
- 系统级 env var 白名单: PATH/HOME/PYTHONPATH/TEMP 等不算漂移
- file_paths 跳过明显的例子路径(含 `foo`/`bar`/`example` 或 <placeholder>)
- 默认 warn-only(CI 不 fail),--strict 才 exit 1
- 单文件 < 300 行,依赖只有 stdlib

用法:
  python scripts/doc_coherence.py --check all
  python scripts/doc_coherence.py --check endpoints,env_vars
  python scripts/doc_coherence.py --format json --output coherence_report.json
  python scripts/doc_coherence.py --check all --strict  # CI gate 模式

输出:
  stdout: text 摘要
  exit 0: 无 finding 或 非 strict 模式
  exit 1: strict 模式且有 finding
  exit 2: 脚本错误
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, List, Set


PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 扫描的文档范围(repo 根 md + docs 根 + workspace-sample wiki)
def _doc_files() -> List[Path]:
    files: List[Path] = []
    # 项目根的主要 md
    for name in ("README.md", "ARCHITECTURE.md", "CHANGELOG.md", "DEV.md"):
        p = PROJECT_ROOT / name
        if p.is_file():
            files.append(p)
    # docs/ 根层的 md(跳过 archive/ 历史归档)
    docs_dir = PROJECT_ROOT / "docs"
    if docs_dir.is_dir():
        for p in sorted(docs_dir.glob("*.md")):
            files.append(p)
    # workspace-sample/wiki(脱敏 demo)
    ws_sample_wiki = PROJECT_ROOT / "workspace-sample" / "wiki"
    if ws_sample_wiki.is_dir():
        for p in sorted(ws_sample_wiki.glob("*.md")):
            files.append(p)
    return files


def _py_files_for_code_scan() -> List[Path]:
    """扫代码里 os.environ 和 router 定义用,跳过测试 / 缓存 / 第三方。"""
    out: List[Path] = []
    skip_parts = {"__pycache__", ".pytest_cache", "tests", ".venv",
                  ".tmp-pytest", "node_modules", "scripts"}
    for p in PROJECT_ROOT.rglob("*.py"):
        rel = p.relative_to(PROJECT_ROOT)
        if any(part in skip_parts for part in rel.parts):
            continue
        out.append(p)
    return out


@dataclass
class Finding:
    check: str              # endpoints / env_vars / file_paths
    severity: str           # warn / error
    message: str
    where: str = ""         # 文件/行号(可选)

    def to_line(self) -> str:
        loc = f" @ {self.where}" if self.where else ""
        return f"  [{self.severity}] {self.message}{loc}"


# ============================================================
# Check 1: endpoints
# ============================================================

_ROUTER_RE = re.compile(r'@(?:router|app)\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)', re.M)
_DOC_API_RE = re.compile(r'`(/api/[a-zA-Z0-9_\-./{}:?=&]+)`')

_ENDPOINT_REFERENCE_DOCS = {
    # Generated experiment report: endpoints are product-under-test specs, not
    # FastAPI routes in this repository.
    "docs/full_prd_endpoint_2026_04_28.md",
    # Design spec: includes future dashboard API shape before implementation.
    "docs/review-funnel-schema.md",
}


def _rel_doc_path(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _collect_route_paths() -> Set[str]:
    """扫 api/routes/*.py 收集 @router.METHOD("path") 的 path, 加 /api prefix(api/main.py 统一挂载)。"""
    routes_dir = PROJECT_ROOT / "api" / "routes"
    paths: Set[str] = set()
    if not routes_dir.is_dir():
        return paths
    for py in routes_dir.rglob("*.py"):
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _ROUTER_RE.finditer(src):
            # main.py 里所有 router 都挂在 /api 下
            paths.add("/api" + m.group(2))
    return paths


def _path_matches(doc_path: str, route_paths: Set[str]) -> bool:
    """允许 path param 差异: 文档可写 /api/x/{id} 或 /api/x/abc,都算命中定义 /api/x/{id}。"""
    # 精确命中
    if doc_path in route_paths:
        return True
    # 去掉 query/fragment
    stripped = doc_path.split("?")[0].split("#")[0].rstrip("/")
    if stripped in route_paths:
        return True
    # path param 模糊匹配: 把文档里的每段和 route 定义的每段对比
    doc_parts = stripped.strip("/").split("/")
    for rp in route_paths:
        rp_parts = rp.strip("/").split("/")
        if len(rp_parts) != len(doc_parts):
            continue
        ok = True
        for d, r in zip(doc_parts, rp_parts):
            if r.startswith("{") and r.endswith("}"):
                continue  # path param 允许任何值
            if d != r:
                ok = False
                break
        if ok:
            return True
    return False


def check_endpoints() -> List[Finding]:
    route_paths = _collect_route_paths()
    if not route_paths:
        return [Finding("endpoints", "error", "未在 api/routes/*.py 里找到任何 @router 定义")]
    findings: List[Finding] = []
    seen: Set[str] = set()
    for md in _doc_files():
        rel = _rel_doc_path(md)
        if rel in _ENDPOINT_REFERENCE_DOCS:
            continue
        try:
            src = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _DOC_API_RE.finditer(src):
            doc_path = m.group(1)
            if doc_path in seen:
                continue
            seen.add(doc_path)
            if not _path_matches(doc_path, route_paths):
                findings.append(Finding(
                    "endpoints", "warn",
                    f"文档提到 endpoint `{doc_path}` 但 FastAPI 路由里不存在",
                    where=rel,
                ))
    return findings


# ============================================================
# Check 2: env_vars
# ============================================================

# match: os.environ.get("VAR"), os.environ["VAR"], os.getenv("VAR")
_ENV_CODE_RE = re.compile(
    r'os\.(?:environ(?:\.get)?|getenv)\s*[\(\[]\s*["\']([A-Z_][A-Z0-9_]*)["\']'
)
# .env.example 的变量声明,注释行也算(# FOO=bar)
_ENV_DECL_RE = re.compile(r'^\s*#?\s*([A-Z_][A-Z0-9_]*)\s*=', re.M)

# 系统级 / 外部工具环境变量,不算漂移
_SYSTEM_WHITELIST = {
    "PATH", "HOME", "USER", "USERNAME", "TEMP", "TMP", "TMPDIR",
    "PYTHONPATH", "PYTHONUNBUFFERED", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE",
    "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN",
    "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_TEST_MODE",
    "WORKSPACE", "GITHUB_ACTIONS", "GITHUB_TOKEN", "CI", "LANG", "LC_ALL",
    "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "SYSTEMROOT", "WINDIR",
    "NODE_ENV", "NEXT_PUBLIC_SSE_BASE", "API_BASE_URL",
    "STATE_DIR", "PECKER_OUTPUT_DIR", "PECKER_TELEMETRY_DIR",
    "PECKER_SESSION_ID",  # 运行时注入
}


def _collect_env_from_code() -> Set[str]:
    found: Set[str] = set()
    for py in _py_files_for_code_scan():
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _ENV_CODE_RE.finditer(src):
            found.add(m.group(1))
    return found


def _collect_env_from_example() -> Set[str]:
    env_path = PROJECT_ROOT / ".env.example"
    if not env_path.is_file():
        return set()
    try:
        src = env_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return set(_ENV_DECL_RE.findall(src))


def check_env_vars() -> List[Finding]:
    code_vars = _collect_env_from_code()
    example_vars = _collect_env_from_example()
    findings: List[Finding] = []

    # 代码读了但 .env.example 没列
    missing = sorted(code_vars - example_vars - _SYSTEM_WHITELIST)
    for v in missing:
        findings.append(Finding(
            "env_vars", "warn",
            f"代码读取了 env 变量 `{v}` 但 .env.example 未列(可能是新加变量忘更新文档)",
            where=".env.example",
        ))

    # .env.example 列了但代码没用(可能是过时变量)
    stale = sorted(example_vars - code_vars - _SYSTEM_WHITELIST)
    for v in stale:
        findings.append(Finding(
            "env_vars", "warn",
            f".env.example 列了 `{v}` 但代码里未找到 os.environ 读取(可能已废弃)",
            where=".env.example",
        ))

    return findings


# ============================================================
# Check 3: file_paths
# ============================================================

# backtick 包裹、明确指向某目录下文件(必须含至少一个 /)、带扩展名,可带 :line
# 故意不扫裸文件名("app.py" 这种简称假阳性太高,只在写作意图 = 精确定位路径时才有意义)
_DOC_PATH_RE = re.compile(
    r'`([a-zA-Z0-9_][a-zA-Z0-9_\-.]*/[a-zA-Z0-9_\-./]+\.(?:py|ts|tsx|jsx|yml|yaml|json|sh|md))(?::\d+(?:-\d+)?)?`'
)

# 跳过示例型引用
_EXAMPLE_TOKENS = {"foo", "bar", "baz", "example", "placeholder", "your_name", "<path>", "xxx"}
_PLANNED_OR_TEMPLATE_TOKENS = ("YYYY", "_template.")
_RESEARCH_DOC_PREFIXES = ("docs/research_",)
_FUTURE_SPEC_DOCS = {
    "docs/nli_dar_wiring_diagnosis_2026_04_26.md",
    "docs/pm-reject-reason-schema.md",
    "docs/review-funnel-schema.md",
    "docs/schema_registry_design_2026_04_27.md",
    "docs/sprint-real-prd-calibration-evidence-governance.md",
    "docs/wiki-frontmatter-v2.md",
}


def _is_expected_non_repo_path(doc_rel: str, path: str) -> bool:
    """Skip references that are intentionally not current repo files."""
    if any(doc_rel.startswith(prefix) for prefix in _RESEARCH_DOC_PREFIXES):
        return True
    if any(token in path for token in _PLANNED_OR_TEMPLATE_TOKENS):
        return True
    if path.startswith("memory/"):
        return True
    if doc_rel in _FUTURE_SPEC_DOCS and path.startswith(
        ("api/routes/", "scripts/", "tests/", "review-rules/")
    ):
        return True
    if doc_rel in _FUTURE_SPEC_DOCS and path.startswith("docs/calibration-report-"):
        return True
    return False


def check_file_paths() -> List[Finding]:
    findings: List[Finding] = []
    seen: Set[tuple] = set()
    for md in _doc_files():
        rel = _rel_doc_path(md)
        try:
            src = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _DOC_PATH_RE.finditer(src):
            path = m.group(1)
            lower = path.lower()
            if any(tok in lower for tok in _EXAMPLE_TOKENS):
                continue
            if _is_expected_non_repo_path(rel, path):
                continue
            key = (str(md), path)
            if key in seen:
                continue
            seen.add(key)
            full = PROJECT_ROOT / path
            if not full.exists():
                findings.append(Finding(
                    "file_paths", "warn",
                    f"文档引用的路径 `{path}` 在仓库中不存在",
                    where=rel,
                ))
    return findings


# ============================================================
# main
# ============================================================

CHECKS = {
    "endpoints": check_endpoints,
    "env_vars": check_env_vars,
    "file_paths": check_file_paths,
}


def _render_text(findings: List[Finding]) -> str:
    if not findings:
        return "doc_coherence: all checks clean (endpoints / env_vars / file_paths)"
    by_check: dict[str, List[Finding]] = {}
    for f in findings:
        by_check.setdefault(f.check, []).append(f)
    lines: List[str] = []
    for check, items in by_check.items():
        lines.append(f"\n[{check}] {len(items)} finding(s):")
        for it in items:
            lines.append(it.to_line())
    lines.append(f"\ntotal: {len(findings)} finding(s)")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    parser.add_argument("--check", default="all",
                        help="逗号分隔: all 或 endpoints,env_vars,file_paths")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--output", help="写入文件,默认 stdout")
    parser.add_argument("--strict", action="store_true",
                        help="有任何 finding 则 exit 1 (CI gate 用)")
    args = parser.parse_args()

    if args.check == "all":
        selected = list(CHECKS.keys())
    else:
        selected = [c.strip() for c in args.check.split(",") if c.strip()]
        bad = [c for c in selected if c not in CHECKS]
        if bad:
            print(f"unknown check: {bad}. available: {list(CHECKS.keys())}", file=sys.stderr)
            return 2

    all_findings: List[Finding] = []
    for c in selected:
        all_findings.extend(CHECKS[c]())

    if args.format == "json":
        payload = {"findings": [asdict(f) for f in all_findings], "count": len(all_findings)}
        rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        rendered = _render_text(all_findings)

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        # Windows 终端 GBK 对中文 tolerant 处理
        try:
            print(rendered)
        except UnicodeEncodeError:
            sys.stdout.buffer.write(rendered.encode("utf-8", errors="replace"))
            sys.stdout.buffer.write(b"\n")

    if args.strict and all_findings:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"doc_coherence error: {e}", file=sys.stderr)
        sys.exit(2)
