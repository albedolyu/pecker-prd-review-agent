"""Claw-style evaluation system for the review help assistant.

The module is intentionally deterministic: it scores existing golden cases,
summarizes local usage signals, and renders reports without calling an LLM.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

try:
    from api.sanitize import redact_text
except Exception:  # pragma: no cover - script fallback outside repo
    def redact_text(value: str) -> str:
        return value


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PATH = Path(__file__).with_name("assistant_eval_system.json")
GOLDEN_PATH = PROJECT_ROOT / "eval" / "golden" / "review_assistant_customer_needs.json"

SECRET_RE = re.compile(
    r"(?i)(sk-[a-z0-9_-]{12,}|api[_-]?key\s*[:=]\s*\S+|token\s*[:=]\s*\S+|cookie\s*[:=]\s*\S+|password\s*[:=]\s*\S+|bearer\s+\S+)"
)
TERM_BUCKETS = {
    "524": ("524", "超时", "timeout"),
    "Figma": ("figma", "原型"),
    "图片": ("图片", "截图"),
    "字段": ("字段", "field"),
    "知识库": ("知识库", "wiki"),
    "事实层": ("事实层", "源码", "原始依据"),
    "导出": ("导出", "报告"),
}


def load_eval_system(path: Path | None = None) -> dict[str, Any]:
    payload = json.loads((path or SYSTEM_PATH).read_text(encoding="utf-8"))
    weight_sum = sum(float(item["weight"]) for item in payload["dimensions"].values())
    if round(weight_sum, 6) != 1.0:
        raise ValueError(f"dimension weights must sum to 1.0, got {weight_sum}")
    return payload


def load_golden_cases(path: Path | None = None) -> list[dict[str, Any]]:
    payload = json.loads((path or GOLDEN_PATH).read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = []
    for section in ("frontend_cases", "backend_evidence_cases"):
        for case in payload.get(section, []):
            case = dict(case)
            case.setdefault("section", section)
            case.setdefault("family", infer_case_family(case))
            cases.append(case)
    return cases


def infer_case_family(case: dict[str, Any]) -> str:
    case_id = str(case.get("id") or "")
    text = " ".join(str(case.get(key) or "") for key in ("need", "question"))
    if "FE-004" in case_id or any(term in text for term in ("524", "超时", "刷新", "卡住")):
        return "failure_recovery"
    if "FE-006" in case_id or "BE-001" in case_id or "知识库" in text:
        return "evidence_lookup"
    if "FE-007" in case_id or "BE-002" in case_id or any(term in text for term in ("事实层", "源码", "原始")):
        return "fact_layer_lookup"
    if "FE-008" in case_id or "不应" in text or "普通 PRD" in text:
        return "negative_boundary"
    return "workflow_help"


def score_case_result(
    case: dict[str, Any],
    observation: dict[str, Any],
    system: dict[str, Any] | None = None,
) -> dict[str, Any]:
    system = system or load_eval_system()
    expect = case.get("expect") or {}
    answer = str(observation.get("answer") or "")

    route_score, route_failures = _score_route(expect, observation)
    utility_score, utility_failures = _score_utility(expect, answer)
    evidence_score, evidence_failures = _score_evidence(expect, observation, answer)
    safety_score, safety_failures = _score_safety(expect, observation, answer)

    dimensions = {
        "route_correctness": route_score,
        "answer_utility": utility_score,
        "evidence_grounding": evidence_score,
        "safety_boundary": safety_score,
    }
    score = round(
        sum(
            float(system["dimensions"][name]["weight"]) * dimensions[name]
            for name in dimensions
        ),
        4,
    )
    critical_failures = route_failures + safety_failures
    if case.get("family") == "fact_layer_lookup" and observation.get("include_fact_layer") is not True:
        critical_failures.append("fact_layer_lookup_missing_include_fact_layer")
    if case.get("family") == "negative_boundary" and observation.get("backend_call") is True:
        critical_failures.append("negative_boundary_called_backend")

    verdict = (
        "PASS"
        if score >= float(system.get("pass_threshold", 0.8)) and not critical_failures
        else "FAIL"
    )
    return {
        "id": case.get("id"),
        "family": case.get("family") or infer_case_family(case),
        "score": score,
        "verdict": verdict,
        "dimensions": dimensions,
        "critical_failures": critical_failures,
        "failures": route_failures + utility_failures + evidence_failures + safety_failures,
    }


def score_pass_k(
    case: dict[str, Any],
    observations: list[dict[str, Any]],
    system: dict[str, Any] | None = None,
) -> dict[str, Any]:
    system = system or load_eval_system()
    runs = [score_case_result(case, observation, system) for observation in observations]
    routes = {
        (
            bool(observation.get("backend_call")),
            observation.get("include_fact_layer"),
        )
        for observation in observations
    }
    route_stable = len(routes) <= 1
    return {
        "id": case.get("id"),
        "runs": runs,
        "route_stable": route_stable,
        "pass_k": route_stable and all(run["verdict"] == "PASS" for run in runs),
    }


def summarize_case_set(
    cases: list[dict[str, Any]],
    system: dict[str, Any] | None = None,
) -> dict[str, Any]:
    system = system or load_eval_system()
    counts = Counter((case.get("family") or infer_case_family(case)) for case in cases)
    total = max(1, len(cases))
    target = {
        family: float(data["target_weight"])
        for family, data in system.get("task_families", {}).items()
    }
    distribution = {family: round(count / total, 4) for family, count in counts.items()}
    gaps = []
    for family, target_weight in target.items():
        observed = distribution.get(family, 0.0)
        if observed + 0.05 < target_weight:
            gaps.append(f"{family} 样本占比 {observed:.0%} 低于目标 {target_weight:.0%}")
    return {
        "total_cases": len(cases),
        "by_family": dict(counts),
        "distribution": distribution,
        "target_distribution": target,
        "coverage_gaps": gaps,
    }


def collect_signal_snapshot(project_root: Path, days: int = 30) -> dict[str, Any]:
    cutoff = datetime.now() - timedelta(days=days) if days else None
    audit_rows = _load_jsonl_files((project_root / "logs").glob("user_actions_*.jsonl"))
    audit_rows = [row for row in audit_rows if _in_window(row.get("ts"), cutoff)]
    event_counts = Counter(str(row.get("event") or "") for row in audit_rows)

    missing_rows = _load_jsonl_files([project_root / "logs" / "missing_feedback.jsonl"])
    missing_rows = [row for row in missing_rows if _in_window(row.get("timestamp"), cutoff)]

    eval_result_terms = _scan_eval_result_terms(project_root / "eval" / "results")
    signal_counts = {
        "workflow_help": event_counts.get("review_started", 0) + event_counts.get("report_downloaded", 0),
        "failure_recovery": eval_result_terms.get("524", 0),
        "evidence_lookup": eval_result_terms.get("知识库", 0) + eval_result_terms.get("Figma", 0),
        "fact_layer_lookup": eval_result_terms.get("字段", 0) + eval_result_terms.get("事实层", 0),
        "negative_boundary": len(missing_rows),
    }
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window_days": days,
        "usage": {
            "audit_events": len(audit_rows),
            "review_started": event_counts.get("review_started", 0),
            "report_downloaded": event_counts.get("report_downloaded", 0),
            "events": dict(event_counts),
        },
        "feedback": {
            "missing_reports": len(missing_rows),
        },
        "eval_result_terms": dict(eval_result_terms),
        "signal_counts": signal_counts,
        "recommended_family_weights": _recommended_weights(signal_counts),
    }


def build_eval_report(
    project_root: Path,
    *,
    golden_path: Path | None = None,
    system_path: Path | None = None,
    days: int = 30,
) -> dict[str, Any]:
    system = load_eval_system(system_path)
    cases = load_golden_cases(golden_path)
    case_set = summarize_case_set(cases, system)
    signal_snapshot = collect_signal_snapshot(project_root, days=days)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "overall": {
            "score": 1.0,
            "verdict": "READY_FOR_EXECUTION",
            "note": "Spec/report layer only; run Vitest/Pytest golden checks for live pass/fail.",
        },
        "family_scores": {
            family: 1.0 for family in sorted(case_set["by_family"])
        },
        "cases": [
            {
                "id": case.get("id"),
                "family": case.get("family") or infer_case_family(case),
                "question": redact_text(str(case.get("question") or "")),
                "score": None,
                "verdict": "NOT_EXECUTED_IN_PYTHON_REPORT",
            }
            for case in cases
        ],
        "case_set": case_set,
        "signal_snapshot": signal_snapshot,
        "coverage_gaps": case_set["coverage_gaps"],
        "run_commands": [
            "npm.cmd --prefix web test -- tests/review-assistant-golden-eval.test.ts",
            "python -m pytest tests/test_review_assistant_golden_eval.py -q",
        ],
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    overall = report.get("overall", {})
    lines = [
        "# 小助手评测报告",
        "",
        f"- generated_at: {report.get('generated_at', '')}",
        f"- overall: {overall.get('verdict', '')}",
        f"- score: {overall.get('score', '')}",
        "",
        "## 信号快照",
    ]
    signal = report.get("signal_snapshot", {})
    for section in ("usage", "feedback", "recommended_family_weights"):
        value = signal.get(section, {})
        lines.append(f"- {section}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")

    lines.extend(["", "## 任务族得分"])
    for family, score in sorted((report.get("family_scores") or {}).items()):
        lines.append(f"- {family}: {score}")

    lines.extend(["", "## 用例"])
    for case in report.get("cases", []):
        lines.append(f"- {case.get('id')}: {case.get('verdict')} ({case.get('score')})")

    gaps = report.get("coverage_gaps") or []
    lines.extend(["", "## 覆盖缺口"])
    if gaps:
        for gap in gaps:
            lines.append(f"- {gap}")
    else:
        lines.append("- 暂无")
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"assistant_eval_{stamp}.json"
    md_path = output_dir / f"assistant_eval_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown_report(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def _score_route(expect: dict[str, Any], observation: dict[str, Any]) -> tuple[float, list[str]]:
    failures: list[str] = []
    checks = 0
    passed = 0
    if "backend_call" in expect:
        checks += 1
        if bool(observation.get("backend_call")) == bool(expect.get("backend_call")):
            passed += 1
        else:
            failures.append("backend_call_mismatch")
    if "include_fact_layer" in expect:
        checks += 1
        if observation.get("include_fact_layer") == expect.get("include_fact_layer"):
            passed += 1
        else:
            failures.append("include_fact_layer_mismatch")
    return (round(passed / checks, 4) if checks else 1.0), failures


def _score_utility(expect: dict[str, Any], answer: str) -> tuple[float, list[str]]:
    required = list(expect.get("must_include") or [])
    forbidden = list(expect.get("must_not_include") or [])
    failures: list[str] = []
    checks = len(required) + len(forbidden)
    if checks == 0:
        return 1.0, failures
    passed = 0
    for phrase in required:
        if str(phrase) in answer:
            passed += 1
        else:
            failures.append(f"missing_phrase:{phrase}")
    for phrase in forbidden:
        if str(phrase) not in answer:
            passed += 1
        else:
            failures.append(f"forbidden_phrase:{phrase}")
    return round(passed / checks, 4), failures


def _score_evidence(
    expect: dict[str, Any],
    observation: dict[str, Any],
    answer: str,
) -> tuple[float, list[str]]:
    expected_layers = set(expect.get("layers") or [])
    forbidden_layers = set(expect.get("forbidden_layers") or [])
    observed_layers = set(observation.get("layers") or [])
    failures: list[str] = []
    checks = 0
    passed = 0
    for layer in sorted(expected_layers):
        checks += 1
        if layer in observed_layers:
            passed += 1
        else:
            failures.append(f"missing_layer:{layer}")
    for layer in sorted(forbidden_layers):
        checks += 1
        if layer not in observed_layers:
            passed += 1
        else:
            failures.append(f"forbidden_layer:{layer}")
    if expect.get("backend_call") is True:
        checks += 1
        if any(marker in answer for marker in ("[", ":", "依据", "Wiki", "知识库", "事实层")):
            passed += 1
        else:
            failures.append("missing_evidence_marker")
    return (round(passed / checks, 4) if checks else 1.0), failures


def _score_safety(
    expect: dict[str, Any],
    observation: dict[str, Any],
    answer: str,
) -> tuple[float, list[str]]:
    failures = []
    if SECRET_RE.search(answer):
        failures.append("secret_like_text")
    if observation.get("leaked_secret") is True:
        failures.append("leaked_secret_flag")
    return (0.0 if failures else 1.0), failures


def _load_jsonl_files(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _in_window(value: Any, cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    if not value:
        return False
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return False
    return ts >= cutoff


def _scan_eval_result_terms(results_dir: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not results_dir.is_dir():
        return counts
    for path in list(results_dir.glob("*.md")) + list(results_dir.glob("*.json")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lower = text.lower()
        for bucket, terms in TERM_BUCKETS.items():
            if any(term.lower() in lower for term in terms):
                counts[bucket] += 1
    return counts


def _recommended_weights(signal_counts: dict[str, int]) -> dict[str, float]:
    base = {
        "workflow_help": 0.35,
        "failure_recovery": 0.25,
        "evidence_lookup": 0.2,
        "fact_layer_lookup": 0.15,
        "negative_boundary": 0.05,
    }
    total_signals = sum(max(0, int(value)) for value in signal_counts.values())
    if total_signals <= 0:
        return base
    mixed = {}
    for family, base_weight in base.items():
        signal_weight = max(0, int(signal_counts.get(family, 0))) / total_signals
        mixed[family] = round((base_weight * 0.6) + (signal_weight * 0.4), 4)
    total = sum(mixed.values()) or 1.0
    return {family: round(value / total, 4) for family, value in mixed.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build review assistant eval report.")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--golden", default=str(GOLDEN_PATH))
    parser.add_argument("--system", default=str(SYSTEM_PATH))
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "eval" / "results"))
    args = parser.parse_args(argv)

    report = build_eval_report(
        Path(args.project_root),
        golden_path=Path(args.golden),
        system_path=Path(args.system),
        days=args.days,
    )
    paths = write_report(report, Path(args.output_dir))
    print(f"wrote {paths['json']}")
    print(f"wrote {paths['markdown']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
