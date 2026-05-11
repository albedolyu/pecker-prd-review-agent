"""Build fact-layer golden samples from existing human-labelled GT sources."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

try:
    from api.sanitize import redact_text
except Exception:  # pragma: no cover - script fallback outside repo
    def redact_text(value: str) -> str:
        return value


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUSINESS_GT_MANIFEST = (
    PROJECT_ROOT / "eval" / "route_eval" / "datasets" / "data" / "business_prd_gt" / "manifest.json"
)
GROUND_TRUTH_DIR = PROJECT_ROOT / "eval" / "ground_truth"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "golden" / "fact_layer_ground_truth_samples.json"
_DEFAULT_FACT_ROOTS = [
    {
        "label": "fengniao_wiki",
        "path": Path(r"C:\Users\20834\Desktop\代码项目\风鸟代码库\wiki"),
    },
    {
        "label": "fengniao_backend",
        "path": Path(r"C:\Users\20834\Desktop\代码项目\RiskBirdApi"),
    },
    {
        "label": "fengniao_frontend",
        "path": Path(r"C:\Users\20834\Desktop\代码项目\riskbird-mobile-vue3"),
    },
]
_SOURCE_TEXT_EXTENSIONS = {
    ".java",
    ".js",
    ".json",
    ".md",
    ".properties",
    ".sql",
    ".ts",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}
_SOURCE_SKIP_DIRS = {
    ".git",
    ".next",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "target",
}
_SOURCE_MAX_FILES_PER_ROOT = 6000
_SOURCE_MAX_FILE_BYTES = 512 * 1024
_SECRET_RE = re.compile(
    r"(?i)(sk-[a-z0-9_-]{12,}|api[_-]?key\s*[:=]\s*\S+|token\s*[:=]\s*\S+|cookie\s*[:=]\s*\S+|password\s*[:=]\s*\S+|bearer\s+\S+)"
)
_SOURCE_FACT_SEEDS = [
    {
        "source_id": "SRC-FN-001",
        "root_labels": {"fengniao_wiki", "wiki"},
        "question": "帮我查事实层：风险搜索接口现在到底支持哪些三级地区字段？",
        "issue": "/query/risk/search 的 SearchRiskReq 支持 level1AreaCode、level2AreaCode、level3AreaCode，旧 region 由后端解析。",
        "terms": ["/query/risk/search", "SearchRiskReq", "level1AreaCode", "level2AreaCode", "level3AreaCode"],
        "path_hints": ["api/移动端API.md"],
    },
    {
        "source_id": "SRC-FN-002",
        "root_labels": {"fengniao_backend", "backend"},
        "question": "帮我查事实层：开放 API 调用日志表和 trace 字段在源码里叫什么？",
        "issue": "开放 API 调用日志实体映射到 t_dataview_skills_user_log，包含 trace_id、response_time 等审计字段。",
        "terms": ["t_dataview_skills_user_log", "trace_id", "response_time"],
        "path_hints": [
            "riskbird-core/src/main/java/com/xinshucredit/riskbird/domain/riskbirdorder/DataviewSkillsUserLog.java",
            "src/DataviewSkillsUserLog.java",
        ],
    },
    {
        "source_id": "SRC-FN-003",
        "root_labels": {"fengniao_frontend", "frontend"},
        "question": "帮我查事实层：高级筛选前端提交给老接口的关键参数是什么？",
        "issue": "高级筛选前端 buildLegacySearchParams 使用 queryType=senior，并把 cSearch_conditionData 放入 aoData。",
        "terms": ["buildLegacySearchParams", "queryType", "senior", "cSearch_conditionData"],
        "path_hints": ["pages/multiCndSearch/services/multiCndSearch.api.js"],
    },
    {
        "source_id": "SRC-FN-004",
        "root_labels": {"fengniao_backend", "backend"},
        "question": "帮我查事实层：爬虫热门企业判断用的缓存 key 和数据库表是什么？",
        "issue": "热门企业判断涉及 PopularEntCache、Redis Hash fn:popular:ent:{entId % 100} 和 t_ent_popular/ent_popular 表。",
        "terms": ["PopularEntCache", "fn:popular:ent", "ent_popular"],
        "path_hints": [
            "doc/技术方案/搜索引擎爬虫自动登录技术方案.md",
            "riskbird-core/src/main/java/com/xinshucredit/riskbird/cache/PopularEntCache.java",
            "riskbird-core/src/main/java/com/xinshucredit/riskbird/bean/entity/riskbirdm/spider/EntPopular.java",
        ],
    },
    {
        "source_id": "SRC-FN-005",
        "root_labels": {"fengniao_backend", "backend"},
        "question": "帮我查事实层：报告导出任务未完成数量的 SQL 是怎么过滤 state 的？",
        "issue": "QibabaReportExportTaskRepository 查询 t_qibaba_report_export_task 时用 state <>2 统计未完成导出数量。",
        "terms": ["t_qibaba_report_export_task", "state <>2", "getUnFinishedCount"],
        "path_hints": [
            "riskbird-core/src/main/java/com/xinshucredit/riskbird/dao/riskbirdm/QibabaReportExportTaskRepository.java",
        ],
    },
    {
        "source_id": "SRC-FN-006",
        "root_labels": {"fengniao_backend", "backend"},
        "question": "帮我查事实层：企业报告里股东信息模块对应哪些导出编码？",
        "issue": "ExportData 中股东相关模块包括 shareHolder、shareHolderYearReport、shareHolderHistory。",
        "terms": ["shareHolder", "shareHolderYearReport", "shareHolderHistory", "股东信息"],
        "path_hints": [
            "riskbird-core/src/main/java/com/xinshucredit/riskbird/utils/exportNew/ExportData.java",
        ],
    },
    {
        "source_id": "SRC-FN-007",
        "root_labels": {"fengniao_wiki", "wiki"},
        "question": "帮我查事实层：联盟商品相关的三张数据库表分别叫什么？",
        "issue": "联盟商品相关表包括 t_fn_union_goods、t_fn_union_goods_fetch_batch、t_fn_union_goods_fetch_rule。",
        "terms": ["t_fn_union_goods", "t_fn_union_goods_fetch_batch", "t_fn_union_goods_fetch_rule"],
        "path_hints": ["entities/数据库模型.md", "modules/联盟商品广告.md"],
    },
]


def build_fact_layer_golden(
    project_root: Path = PROJECT_ROOT,
    *,
    fact_roots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return deterministic fact-layer golden samples from labelled GT files.

    ``active`` cases come from PM-labelled planted bugs or PM-confirmed true
    positives. ``candidate`` cases are useful seeds, but still need PM review
    before they should influence strict accuracy metrics.
    """
    cases = []
    cases.extend(_business_prd_gt_cases(project_root))
    cases.extend(_pm_decision_cases(project_root))
    cases.extend(_source_verified_fact_cases(_resolve_fact_roots(fact_roots)))

    for index, case in enumerate(cases, start=1):
        case["id"] = f"FLGT-{index:03d}"

    active_count = sum(1 for case in cases if case["activation"] == "active")
    candidate_count = sum(1 for case in cases if case["activation"] == "candidate")
    source_verified_count = sum(
        1 for case in cases if case["source"]["authority"] == "source_verified"
    )
    return {
        "name": "fact_layer_ground_truth_samples",
        "version": "v1",
        "description": (
            "从现有人工标注/PM确认的评审标准答案中抽取事实层小助手黄金样本；"
            "active 可纳入准确率，candidate 仅用于补标队列。"
        ),
        "source_policy": {
            "active": [
                "eval/test_cases/*_planted.json 中 manifest 标记 PM 已标注的 planted_bugs",
                "eval/ground_truth/*.json 中 action=accept/edit 且 is_true_positive=true 且有 note 的 PM 决策",
                "当前数据库/代码库/接口文档事实文件中可直接定位路径和关键词的 source_verified 样本",
            ],
            "candidate": [
                "business_prd_gt manifest inline_minimal 中明确待 PM 后续标注的历史抽取样本",
            ],
            "excluded": [
                "缺少 issue/note 的 PM 决策只说明真假，不足以形成可回答的事实层标准答案",
                "advisor_conflicts 中 is_placeholder=true 的冲突调解样本暂不进入本文件",
            ],
        },
        "metrics_contract": {
            "route_correctness": "问题必须触发 include_fact_layer=true",
            "recall_at_5": "前 5 条证据应命中 expected_sources 中的 source_id 或 path_contains",
            "evidence_grounding": "回答必须引用 location/issue/keywords 中的标准答案要素",
            "safety_boundary": "不得泄露 PRD 原文大段内容、密钥、cookie、token 或未脱敏路径",
        },
        "active_case_count": active_count,
        "candidate_case_count": candidate_count,
        "source_verified_case_count": source_verified_count,
        "cases": cases,
    }


def write_fact_layer_golden(
    output_path: Path = DEFAULT_OUTPUT,
    project_root: Path = PROJECT_ROOT,
    *,
    fact_roots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = build_fact_layer_golden(project_root, fact_roots=fact_roots)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def _source_verified_fact_cases(fact_roots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for seed in _SOURCE_FACT_SEEDS:
        hit = _find_source_hit(seed, fact_roots)
        if not hit:
            continue
        cases.append(
            _make_case(
                workspace=str(hit["root_label"]),
                question=str(seed["question"]),
                source={
                    "kind": "source_verified_fact",
                    "authority": "source_verified",
                    "activation_reason": _activation_reason("source_verified"),
                    "path": str(hit["relative_path"]),
                    "source_id": str(seed["source_id"]),
                    "root_label": str(hit["root_label"]),
                    "line": hit["line"],
                },
                standard_answer={
                    "location": f"{hit['relative_path']}:{hit['line']}",
                    "issue": str(seed["issue"]),
                    "severity": "fact",
                    "type": "source_verified",
                    "keywords": _string_list(seed.get("terms")),
                    "snippet": str(hit["snippet"]),
                },
                activation="active",
            )
        )
    return cases


def _business_prd_gt_cases(project_root: Path) -> list[dict[str, Any]]:
    manifest_path = (
        project_root / "eval" / "route_eval" / "datasets" / "data" / "business_prd_gt" / "manifest.json"
    )
    manifest = _read_json(manifest_path)
    cases: list[dict[str, Any]] = []
    for entry in manifest.get("entries", []):
        gt_source = str(entry.get("gt_source") or "")
        authority = "pm_labeled" if gt_source == "planted_bugs" else "seed_needs_pm_review"
        activation = "active" if authority == "pm_labeled" else "candidate"
        source_path = entry.get("gt_path") or str(manifest_path.relative_to(project_root))
        ground_truth = _entry_ground_truth(project_root, entry)
        for gt in ground_truth:
            issue = str(gt.get("issue") or gt.get("description") or "").strip()
            if not issue:
                continue
            cases.append(
                _make_case(
                    workspace=str(entry.get("workspace") or ""),
                    question=_question_for(entry, gt),
                    source={
                        "kind": "business_prd_gt",
                        "authority": authority,
                        "activation_reason": _activation_reason(authority),
                        "path": source_path,
                        "source_id": str(gt.get("rule_id") or gt.get("id") or ""),
                        "prd_path": str(entry.get("prd_path") or ""),
                    },
                    standard_answer={
                        "location": str(gt.get("location") or ""),
                        "issue": issue,
                        "severity": str(gt.get("severity") or ""),
                        "type": str(gt.get("type") or ""),
                        "keywords": _string_list(gt.get("keywords")),
                    },
                    activation=activation,
                )
            )
    return cases


def _pm_decision_cases(project_root: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    gt_dir = project_root / "eval" / "ground_truth"
    for path in sorted(gt_dir.glob("*.json")):
        payload = _read_json(path)
        workspace = str(payload.get("workspace") or "")
        reviewer = str(payload.get("reviewer") or "")
        for item in payload.get("items", []):
            action = str(item.get("action") or "")
            note = str(item.get("note") or item.get("reason_note") or "").strip()
            if action not in {"accept", "edit"} or item.get("is_true_positive") is not True or not note:
                continue
            cases.append(
                _make_case(
                    workspace=workspace,
                    question=_question_for_pm_decision(item, workspace),
                    source={
                        "kind": "pm_decision_ground_truth",
                        "authority": "pm_confirmed_true_positive",
                        "activation_reason": _activation_reason("pm_confirmed_true_positive"),
                        "path": str(path.relative_to(project_root)),
                        "source_id": str(item.get("id") or ""),
                        "reviewer": reviewer,
                    },
                    standard_answer={
                        "location": str(item.get("location") or ""),
                        "issue": note,
                        "severity": str(item.get("severity") or ""),
                        "type": str(item.get("dimension") or ""),
                        "keywords": _keywords_from_pm_item(item, note),
                    },
                    activation="active",
                )
            )
    return cases


def _resolve_fact_roots(fact_roots: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if fact_roots is None:
        raw = os.environ.get("PECKER_FACT_SOURCE_ROOTS", "").strip()
        if raw:
            fact_roots = []
            for item in raw.split(";"):
                if not item.strip():
                    continue
                if "=" in item:
                    label, path = item.split("=", 1)
                else:
                    path = item
                    label = Path(path).name or "source"
                fact_roots.append({"label": label.strip(), "path": Path(path.strip())})
        else:
            fact_roots = _DEFAULT_FACT_ROOTS

    roots: list[dict[str, Any]] = []
    for root in fact_roots:
        path = Path(root["path"])
        if path.is_dir():
            roots.append({"label": str(root["label"]), "path": path})
    return roots


def _find_source_hit(seed: dict[str, Any], fact_roots: list[dict[str, Any]]) -> dict[str, Any] | None:
    root_labels = set(seed.get("root_labels") or [])
    terms = _string_list(seed.get("terms"))
    path_hints = _string_list(seed.get("path_hints"))
    hinted_candidates: list[dict[str, Any]] = []
    scanned_candidates: list[dict[str, Any]] = []

    for root in fact_roots:
        label = str(root["label"])
        if root_labels and label not in root_labels:
            continue
        path = Path(root["path"])
        for file_path in _hinted_source_files(path, path_hints):
            hit = _source_file_hit(label, path, file_path, terms)
            if hit:
                hit["score"] = _source_hit_score(str(hit["relative_path"]), path_hints)
                hinted_candidates.append(hit)

    if hinted_candidates:
        return _best_source_hit(hinted_candidates)

    for root in fact_roots:
        label = str(root["label"])
        if root_labels and label not in root_labels:
            continue
        path = Path(root["path"])
        for file_path in _iter_source_files(path):
            hit = _source_file_hit(label, path, file_path, terms)
            if hit:
                hit["score"] = _source_hit_score(str(hit["relative_path"]), path_hints)
                scanned_candidates.append(hit)
    return _best_source_hit(scanned_candidates)


def _hinted_source_files(root: Path, path_hints: list[str]) -> Iterable[Path]:
    seen: set[Path] = set()
    for hint in path_hints:
        candidate = root / Path(hint)
        if candidate in seen or not candidate.is_file():
            continue
        seen.add(candidate)
        yield candidate


def _source_file_hit(label: str, root: Path, file_path: Path, terms: list[str]) -> dict[str, Any] | None:
    try:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if not _contains_all_terms(text, terms):
        return None
    line, snippet = _best_source_snippet(text, terms)
    try:
        relative_path = str(file_path.relative_to(root)).replace("\\", "/")
    except ValueError:
        relative_path = file_path.name
    return {
        "root_label": label,
        "relative_path": relative_path,
        "line": line,
        "snippet": snippet,
    }


def _best_source_hit(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda hit: (-int(hit.get("score", 0)), str(hit.get("relative_path", ""))),
    )[0]


def _source_hit_score(relative_path: str, path_hints: list[str]) -> int:
    score = _path_hint_score(relative_path, path_hints)
    normalized_path = _normalize_source_path(relative_path)
    if normalized_path.endswith("log.md"):
        score -= 100
    if "/test/" in normalized_path or normalized_path.endswith("test.java"):
        score -= 20
    return score


def _path_hint_score(relative_path: str, path_hints: list[str]) -> int:
    normalized_path = _normalize_source_path(relative_path)
    for index, hint in enumerate(path_hints):
        normalized_hint = _normalize_source_path(hint)
        if normalized_path == normalized_hint:
            return 2000 - index
        if normalized_path.endswith("/" + normalized_hint) or normalized_path.endswith(normalized_hint):
            return 1900 - index
        if normalized_hint and normalized_hint in normalized_path:
            return 1800 - index
    return 0


def _normalize_source_path(path: str) -> str:
    return path.replace("\\", "/").strip("/").lower()


def _iter_source_files(root: Path) -> Iterable[Path]:
    seen = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in _SOURCE_SKIP_DIRS:
                    stack.append(entry)
                continue
            if entry.suffix.lower() not in _SOURCE_TEXT_EXTENSIONS:
                continue
            try:
                if entry.stat().st_size > _SOURCE_MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield entry
            seen += 1
            if seen >= _SOURCE_MAX_FILES_PER_ROOT:
                return


def _contains_all_terms(text: str, terms: list[str]) -> bool:
    lower = text.lower()
    return all(term.lower() in lower for term in terms)


def _best_source_snippet(text: str, terms: list[str]) -> tuple[int, str]:
    lines = text.splitlines()
    evidence_lines: list[tuple[int, str]] = []
    covered: set[str] = set()
    normalized_terms = [(term, term.lower()) for term in terms]
    for index, line in enumerate(lines, start=1):
        if _SECRET_RE.search(line):
            continue
        lower = line.lower()
        matched = {term for term, normalized in normalized_terms if normalized in lower}
        if not matched:
            continue
        if matched - covered or not evidence_lines:
            evidence_lines.append((index, line))
            covered.update(matched)
        if len(covered) == len(terms):
            break

    if evidence_lines:
        best_line = evidence_lines[0][0]
        snippet = " | ".join(line for _, line in evidence_lines)
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if len(snippet) > 360:
            snippet = snippet[:357] + "..."
        return best_line, redact_text(snippet)

    best_line = 1
    best_score = -1
    best_text = ""
    for index, line in enumerate(lines, start=1):
        lower = line.lower()
        score = sum(1 for term in terms if term.lower() in lower)
        if _SECRET_RE.search(line):
            score -= 100
        if score > best_score:
            best_line = index
            best_score = score
            best_text = line
    snippet = re.sub(r"\s+", " ", best_text).strip()
    if len(snippet) > 360:
        snippet = snippet[:357] + "..."
    return best_line, redact_text(snippet)


def _entry_ground_truth(project_root: Path, entry: dict[str, Any]) -> list[dict[str, Any]]:
    gt_path = entry.get("gt_path")
    if not gt_path:
        return list(entry.get("inline_ground_truth") or [])
    raw = _read_json(project_root / gt_path)
    if isinstance(raw, dict) and "planted_bugs" in raw:
        return [
            {
                "rule_id": bug.get("id"),
                "issue": bug.get("description", ""),
                "severity": bug.get("severity", ""),
                "location": bug.get("location", ""),
                "type": bug.get("type", ""),
                "keywords": bug.get("keywords", []),
            }
            for bug in raw.get("planted_bugs", [])
        ]
    if isinstance(raw, list):
        return raw
    return []


def _make_case(
    *,
    workspace: str,
    question: str,
    source: dict[str, Any],
    standard_answer: dict[str, Any],
    activation: str,
) -> dict[str, Any]:
    keywords = _string_list(standard_answer.get("keywords"))[:5]
    must_include = [
        value
        for value in [
            str(source.get("source_id") or ""),
            str(standard_answer.get("location") or ""),
            *keywords[:3],
        ]
        if value
    ]
    return {
        "family": "fact_layer_lookup",
        "activation": activation,
        "workspace": workspace,
        "question": question,
        "source": source,
        "standard_answer": standard_answer,
        "expected_sources": [
            {
                "path_contains": source["path"],
                "source_id": source.get("source_id", ""),
                "must_include_terms": keywords,
            }
        ],
        "expect": {
            "backend_call": True,
            "include_fact_layer": True,
            "must_include": must_include,
            "must_not_include": [
                "我猜",
                "可能是",
                "无法确定但可以假设",
            ],
        },
    }


def _question_for(entry: dict[str, Any], gt: dict[str, Any]) -> str:
    workspace = str(entry.get("workspace") or "这个 PRD")
    topic = _topic(gt)
    return f"帮我查事实层标准答案：{workspace} 里「{topic}」这条应该怎么判？"


def _question_for_pm_decision(item: dict[str, Any], workspace: str) -> str:
    location = str(item.get("location") or "这条评审项")
    rule_id = str(item.get("rule_id") or item.get("id") or "")
    topic = f"{rule_id} {location}".strip()
    return f"帮我查事实层标准答案：{workspace or '当前 workspace'} 里「{topic}」这条 PM 是怎么标的？"


def _topic(gt: dict[str, Any]) -> str:
    keywords = _string_list(gt.get("keywords"))
    if keywords:
        return " / ".join(keywords[:3])
    issue = str(gt.get("issue") or gt.get("description") or "")
    return issue[:28] if issue else str(gt.get("rule_id") or gt.get("id") or "标准答案")


def _keywords_from_pm_item(item: dict[str, Any], note: str) -> list[str]:
    values = [
        str(item.get("rule_id") or ""),
        str(item.get("dimension") or ""),
        str(item.get("severity") or ""),
    ]
    values.extend(piece.strip() for piece in note.replace(";", "；").split("；")[:3])
    return [value for value in values if value]


def _activation_reason(authority: str) -> str:
    if authority == "pm_labeled":
        return "manifest 明确标记 PM 已标注，可进入事实层准确率评估"
    if authority == "pm_confirmed_true_positive":
        return "PM 决策已确认 true positive，且 note 可作为标准答案摘要"
    if authority == "source_verified":
        return "当前事实文件可直接定位路径、行号和关键词，可进入事实层检索准确率评估"
    return "历史 review_items 抽取的最小 GT，manifest 明确待 PM 后续标注，先作为候选样本"


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    if value:
        return [str(value)]
    return []


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build fact-layer golden samples.")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)

    payload = write_fact_layer_golden(Path(args.output), Path(args.project_root))
    print(
        "wrote "
        f"{args.output} "
        f"(active={payload['active_case_count']}, candidate={payload['candidate_case_count']})"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
