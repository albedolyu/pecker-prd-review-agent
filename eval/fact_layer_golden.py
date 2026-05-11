"""Build fact-layer golden samples from existing human-labelled GT sources."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUSINESS_GT_MANIFEST = (
    PROJECT_ROOT / "eval" / "route_eval" / "datasets" / "data" / "business_prd_gt" / "manifest.json"
)
GROUND_TRUTH_DIR = PROJECT_ROOT / "eval" / "ground_truth"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "golden" / "fact_layer_ground_truth_samples.json"


def build_fact_layer_golden(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Return deterministic fact-layer golden samples from labelled GT files.

    ``active`` cases come from PM-labelled planted bugs or PM-confirmed true
    positives. ``candidate`` cases are useful seeds, but still need PM review
    before they should influence strict accuracy metrics.
    """
    cases = []
    cases.extend(_business_prd_gt_cases(project_root))
    cases.extend(_pm_decision_cases(project_root))

    for index, case in enumerate(cases, start=1):
        case["id"] = f"FLGT-{index:03d}"

    active_count = sum(1 for case in cases if case["activation"] == "active")
    candidate_count = sum(1 for case in cases if case["activation"] == "candidate")
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
        "cases": cases,
    }


def write_fact_layer_golden(
    output_path: Path = DEFAULT_OUTPUT,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    payload = build_fact_layer_golden(project_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


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
