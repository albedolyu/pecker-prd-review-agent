#!/usr/bin/env python
"""啄木鸟 Rule Regression Harness — promptfoo 风格的规则级 P/R 回归.

设计目标 (与 cuckoo_eval.py 共存,不替代):
  - cuckoo_eval.py 是手卷 eval 工具,跟规则没强绑定,无 P/R baseline 概念
  - 本 harness 把每条规则的 positive_example / negative_example 当 promptfoo 的
    test case + assertion, 一条规则一条规则跑 worker,产出 precision / recall

输入: 带 positive_example + negative_example 字段的 yaml (升级后的 review-checklist.yaml
      或 fixtures/regression_demo.yaml).

流程 (per rule):
  1. positive case: worker 跑 positive_example.snippet → 期望 worker 报出 rule_id (TP)
                     报出但 evidence 与 fire_when 语义不对齐 (二层 NLI) → 降级 FP
                     未报出 → FN
  2. negative case: worker 跑 negative_example.snippet → 期望 worker 不报 rule_id (TN)
                     报出 → FP

输出:
  - results.json (机器可读, 含每条规则 TP/FP/FN/TN + macro P/R)
  - 友好 stdout 报告

回归 gate:
  - 第一次跑无 baseline.json → 直接当 baseline, warn 提示
  - 后续跑: 任一规则 P 或 R 下降 > tolerance (默认 0.05 绝对差) → exit 1
  - --update-baseline 显式 promote 当前结果

CLI:
    python scripts/rule_regression.py \
        [--rules-yaml PATH]            (默认: workspace/review-rules/review-checklist.yaml)
        [--baseline PATH]              (默认: scripts/fixtures/regression_baseline.json)
        [--update-baseline]            (覆盖 baseline)
        [--tolerance 0.05]             (P/R 下降容忍阈值)
        [--output PATH]                (results.json 路径)
        [--skip-nli]                   (跳过二层 NLI 校验, 加速 dev)
        [--rule-id ID]                 (只跑指定规则, 调试用)
        [--dry-run]                    (只验证 yaml 加载 + 不调 LLM)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

# 让 scripts/ 目录运行时能 import 项目根
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 2026-04-28: 必须 load .env 才能读 DEEPSEEK_API_KEY (verify.nli 切 DeepSeek 后)
from dotenv import load_dotenv
load_dotenv(os.path.join(_ROOT, ".env"), override=True)

import yaml

from logger import get_logger

log = get_logger("rule_regression")


# ============================================================
# 数据结构
# ============================================================

@dataclass
class RuleCaseResult:
    """单条规则一次 case (positive 或 negative) 的结果"""
    reported: bool                          # worker 是否报了 rule_id
    evidence_aligned: Optional[bool] = None  # NLI 校验结果 (None = 没跑)
    error: Optional[str] = None             # worker 调用异常时填
    worker_finding_count: int = 0           # worker 总共报了多少条 finding (debug 用)
    matched_finding: Optional[Dict[str, Any]] = None  # 命中的那条 finding (debug 用)


@dataclass
class RuleResult:
    """单条规则的完整结果 (positive + negative + 聚合指标)"""
    rule_id: str
    dimension: str
    positive_case: Optional[RuleCaseResult] = None
    negative_case: Optional[RuleCaseResult] = None

    # 混淆矩阵 (二分类: 这条规则是否应该被报)
    TP: int = 0
    FP: int = 0
    FN: int = 0
    TN: int = 0

    @property
    def precision(self) -> float:
        denom = self.TP + self.FP
        return self.TP / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.TP + self.FN
        return self.TP / denom if denom else 0.0

    @property
    def has_error(self) -> bool:
        """positive 或 negative 任一 worker 调用抛异常 → 该规则视为无有效信号"""
        if self.positive_case and self.positive_case.error:
            return True
        if self.negative_case and self.negative_case.error:
            return True
        return False

    @property
    def error_summary(self) -> Optional[str]:
        """汇总两个 case 的错误, 给 errors.json 用"""
        parts = []
        if self.positive_case and self.positive_case.error:
            parts.append(f"positive: {self.positive_case.error}")
        if self.negative_case and self.negative_case.error:
            parts.append(f"negative: {self.negative_case.error}")
        return " | ".join(parts) if parts else None


# ============================================================
# baseline schema version
# ============================================================
# v1: 没有 schema_version 字段, 把崩溃规则的 P/R=0 当真实信号 (污染)
# v2: 加 schema_version, status=error 时 P/R=null 不进入 macro, errors 单写一个 json
BASELINE_SCHEMA_VERSION = 2


# ============================================================
# 加载: rules + dimensions
# ============================================================

def load_rules_with_examples(rules_yaml_path: str) -> List[Dict[str, Any]]:
    """加载有 positive_example 字段的规则 (negative_example 可选)。

    支持三种 yaml schema:
      1. 升级后的 review-checklist.yaml (inline): rules[].positive_example/negative_example
      2. SSOT extends 模式 (workspace yaml): extends: ../../review-rules-shared/...
         走 review.rule_loader 解析 extends 链
      3. demo fixture: 同 1
    """
    if not os.path.exists(rules_yaml_path):
        raise FileNotFoundError(f"规则 yaml 不存在: {rules_yaml_path}")

    # 2026-04-29: SSOT extends 支持 — 优先走 rule_loader, 它会 resolve extends + merge additional_rules
    # 老 inline yaml (无 extends) 也兼容 (rule_loader fallback 直接读 rules 字段)
    rules = []
    try:
        from review.rule_loader import load_review_checklist
        # rule_loader 接 workspace 路径或 yaml 路径都行 — 这里推断 workspace 从 yaml 路径
        ws_path = os.path.dirname(os.path.dirname(os.path.abspath(rules_yaml_path)))
        if os.path.basename(os.path.dirname(rules_yaml_path)) == "review-rules":
            rules = load_review_checklist(ws_path) or []
            log.info(f"通过 rule_loader 加载 {len(rules)} 条规则 (含 SSOT extends)")
    except Exception as e:
        log.warning(f"rule_loader 失败, 回退 inline yaml 加载: {e}")

    # rule_loader 失败或拿到 0 条 → 回退老路径
    if not rules:
        with open(rules_yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        rules = data.get("rules", []) or []
    valid: List[Dict[str, Any]] = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        if not r.get("id"):
            log.warning(f"跳过无 id 规则: {r}")
            continue
        if not r.get("positive_example"):
            log.info(f"跳过无 positive_example 规则: {r['id']}")
            continue
        # snippet 必填
        pos = r["positive_example"]
        if not isinstance(pos, dict) or not pos.get("snippet"):
            log.warning(f"规则 {r['id']} 的 positive_example 缺 snippet, 跳过")
            continue
        valid.append(r)

    log.info(f"加载到 {len(valid)} 条带 example 的规则 (源: {rules_yaml_path})")
    return valid


def build_rule_to_dimension_map() -> Dict[str, str]:
    """从 review-dimensions.yaml 构建 rule_id → dim_key 反查表 (走 review.dimensions 单点)."""
    from review.dimensions import get_review_dimensions
    dims = get_review_dimensions()
    rule_to_dim: Dict[str, str] = {}
    for dim_key, dim_cfg in dims.items():
        for r in dim_cfg.get("checklist", []) or []:
            rid = r.get("rule_id")
            if rid:
                rule_to_dim[rid] = dim_key
    log.info(f"rule_to_dimension 反查表: {len(rule_to_dim)} 条")
    return rule_to_dim


# ============================================================
# Worker 调用封装
# ============================================================

def run_worker_on_snippet(
    dim_key: str,
    snippet: str,
) -> List[Dict[str, Any]]:
    """对单段 PRD snippet 跑指定维度的 worker, 返回 worker items 列表。

    复用 review.worker._worker_core, 不重新实现 Claude API 调用 / route_call.
    snippet 当作完整 PRD 内容传, wiki_pages 给空 dict (regression 不依赖 wiki).
    """
    from review.worker import _worker_core
    # client=None 让 _worker_core 走 model_router.route_call("worker.<dim>")
    result = _worker_core(
        client=None,
        dim_key=dim_key,
        prd_content=snippet,
        wiki_pages={},
        model_tiers={},                  # deprecated 入参, 路由走 route_id
        rule_perf_history=None,
        wiki_path=None,
        diff_context=None,
        on_tool_call=None,
    )
    return result.get("items", []) or []


def find_finding_by_rule_id(items: List[Dict[str, Any]], rule_id: str) -> Optional[Dict[str, Any]]:
    """从 worker items 里找第一条 rule_id 匹配的 finding"""
    for item in items:
        if item.get("rule_id") == rule_id:
            return item
    return None


# ============================================================
# 二层 LLM-as-judge: NLI 校验 evidence 是否对齐 fire_when
# ============================================================

def check_evidence_alignment(
    rule: Dict[str, Any],
    finding: Dict[str, Any],
    n_samples: int = 4,
    max_signal_threshold: float = 0.6,
) -> bool:
    """对 worker TP 做二层校验: evidence 是否真对应 rule.fire_when 的语境。

    走 verify.nli (Haiku, 多采样投票). 如果 entail 信号 < threshold 视为不对齐,
    把这条 TP 在 caller 处降级为 FP.

    实现说明: 直接复用 verify.nli route 但伪装成 nli 输入格式 — premise 用规则
    fire_when + description 拼接, hypothesis 用 worker finding 的 issue + evidence_content.
    没用 evidence_verify._llm_nli_score 因为它依赖 wiki_pages 上下文,我们这里
    只做规则语义对齐,跟 wiki 无关。
    """
    from model_router import route_call
    import re

    fire_when = rule.get("fire_when", "")
    description = rule.get("description", "")
    issue = finding.get("issue", "")
    evidence = finding.get("evidence_content", "")

    if not fire_when or not issue:
        # 缺关键字段, 默认对齐 (避免误报)
        return True

    system = (
        "你判断 worker 报告的 PRD 问题是否真对应给定规则的触发条件。\n\n"
        "三选一:\n"
        "- entail: worker 报告的问题语义上确实是该规则要 catch 的场景\n"
        "- contradict: worker 报告的问题与规则触发条件无关或方向相反\n"
        "- neutral: 沾边但不能确定是不是这条规则要 catch 的\n\n"
        '只输出 JSON 一行: {"verdict": "entail|contradict|neutral", "reason": "<具体理由>"}'
    )
    user = (
        f"# 规则\n"
        f"规则编号: {rule.get('id')}\n"
        f"规则描述: {description}\n"
        f"触发条件 (fire_when): {fire_when}\n\n"
        f"# Worker 报告的问题\n"
        f"问题描述: {issue}\n"
        f"引用依据: {evidence}\n"
    )

    # 2026-04-28: verdict 解析三层 fallback (与 evidence_verify._llm_nli_score 对齐)
    #  1. JSON 形式: "verdict": "contradict"
    #  2. 无引号/单引号: verdict: contradict
    #  3. 单词扫描: 文本里出现明确 contradict/entail/neutral 词
    # 缺第 3 层会导致 Haiku 输出 markdown 块或解释性文本时全部 reject -> n=0 假失败.
    debug_on = os.environ.get("PECKER_NLI_DEBUG", "0") == "1"
    counts = {"entail": 0, "contradict": 0, "neutral": 0}
    succeeded = 0
    debug_samples = []
    for _ in range(n_samples):
        try:
            resp = route_call(
                "verify.nli",
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=600,  # 2026-04-29: 200 太小, DeepSeek NLI reason 字段常被截断 → fallback 走单词扫描有信号但损失精度
                temperature=0.7,
            )
            text_parts = []
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    text_parts.append(getattr(block, "text", ""))
            text = "".join(text_parts)

            verdict = None
            m = re.search(
                r'["\']?verdict["\']?\s*[:：]\s*["\']?(entail|contradict|neutral)["\']?',
                text, re.IGNORECASE,
            )
            if m:
                verdict = m.group(1).lower()
            else:
                # 第 3 层 fallback: 单词扫描 (Haiku 输出格式抖动时救命)
                for w in ("contradict", "entail", "neutral"):
                    if re.search(rf"\b{w}\b", text, re.IGNORECASE):
                        verdict = w
                        break
            if not verdict:
                if debug_on:
                    debug_samples.append({"reject": "no_verdict", "text": text[:300]})
                continue
            counts[verdict] += 1
            succeeded += 1
        except Exception as e:
            log.warning(f"NLI 校验单次采样失败 ({rule.get('id')}): {str(e)[:80]}")
            continue

    if succeeded == 0:
        # NLI 全失败, 默认对齐 (保守, 不误降 TP→FP)
        log.warning(f"NLI 全采样失败 ({rule.get('id')}), 默认 evidence_aligned=True")
        if debug_on and debug_samples:
            for ds in debug_samples[:2]:
                log.warning(f"  [debug] reject={ds.get('reject')} text={ds.get('text', '')[:200]}")
        return True

    entail_score = counts["entail"] / succeeded
    log.info(
        f"NLI {rule.get('id')}: entail={counts['entail']}/{succeeded} "
        f"contradict={counts['contradict']} neutral={counts['neutral']} "
        f"score={entail_score:.2f} threshold={max_signal_threshold}"
    )
    return entail_score >= max_signal_threshold


# ============================================================
# 单条规则 evaluator
# ============================================================

def evaluate_rule(
    rule: Dict[str, Any],
    dim_key: str,
    *,
    skip_nli: bool = False,
    dry_run: bool = False,
) -> RuleResult:
    """对单条规则跑 positive + negative case, 计算 TP/FP/FN/TN."""
    rid = rule["id"]
    result = RuleResult(rule_id=rid, dimension=dim_key)

    # ---------- positive case ----------
    pos_snippet = rule["positive_example"]["snippet"]
    if dry_run:
        log.info(f"[dry-run] {rid} positive: skipping worker call")
        result.positive_case = RuleCaseResult(reported=True, evidence_aligned=True)
        result.TP = 1
    else:
        try:
            items = run_worker_on_snippet(dim_key, pos_snippet)
            matched = find_finding_by_rule_id(items, rid)
            case = RuleCaseResult(
                reported=matched is not None,
                worker_finding_count=len(items),
                matched_finding=matched,
            )
            if matched:
                # 二层 NLI 校验
                if skip_nli:
                    case.evidence_aligned = True
                else:
                    try:
                        case.evidence_aligned = check_evidence_alignment(rule, matched)
                    except Exception as e:
                        log.warning(f"{rid} NLI 校验异常: {str(e)[:120]}")
                        case.evidence_aligned = True  # 保守 fallback
                if case.evidence_aligned:
                    result.TP = 1
                else:
                    # 报了但 evidence 不对齐 → 降级 FP (报错语境)
                    result.FP += 1
                    log.warning(f"{rid} positive case: 报了但 NLI 不对齐, 降级为 FP")
            else:
                # 没报 → FN
                result.FN = 1
            result.positive_case = case
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            log.error(f"{rid} positive worker 调用失败: {err}\n{traceback.format_exc()}")
            result.positive_case = RuleCaseResult(reported=False, error=err)
            # worker 调失败不计 FN/FP, 只记 error (避免把基础设施故障当成模型问题)

    # ---------- negative case ----------
    neg = rule.get("negative_example") or {}
    neg_snippet = neg.get("snippet") if isinstance(neg, dict) else None
    if not neg_snippet:
        log.info(f"{rid} 无 negative_example, 跳过")
    elif dry_run:
        log.info(f"[dry-run] {rid} negative: skipping worker call")
        result.negative_case = RuleCaseResult(reported=False)
        result.TN = 1
    else:
        try:
            items = run_worker_on_snippet(dim_key, neg_snippet)
            matched = find_finding_by_rule_id(items, rid)
            case = RuleCaseResult(
                reported=matched is not None,
                worker_finding_count=len(items),
                matched_finding=matched,
            )
            if matched:
                # negative case 不该报却报了 → FP
                result.FP += 1
            else:
                result.TN = 1
            result.negative_case = case
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            log.error(f"{rid} negative worker 调用失败: {err}")
            result.negative_case = RuleCaseResult(reported=False, error=err)

    return result


# ============================================================
# 聚合 + 输出
# ============================================================

def serialize_results(rule_results: List[RuleResult]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """规则级结果聚合成 (results, errors) 两个 JSON dict.

    schema v2 区别:
    - 任一 case 有 error (worker 异常) → 该规则 status='error', P/R 写 null, **不进 macro**
    - 否则 status='ok', 走原 P/R 计算

    errors dict 单写: { schema_version, generated_at, errors: { rule_id: {dimension, reason, ...} } }
    让用户一眼看出"哪些规则没有有效信号"。
    """
    rules_dict: Dict[str, Any] = {}
    errors_dict: Dict[str, Any] = {}
    p_list: List[float] = []
    r_list: List[float] = []
    ok_count = 0
    error_count = 0

    for rr in rule_results:
        if rr.has_error:
            # 不写 P/R 数值, 标 status=error
            rules_dict[rr.rule_id] = {
                "dimension": rr.dimension,
                "status": "error",
                "TP": rr.TP, "FP": rr.FP, "FN": rr.FN, "TN": rr.TN,
                "precision": None,
                "recall": None,
                "positive_case": _case_to_dict(rr.positive_case),
                "negative_case": _case_to_dict(rr.negative_case),
            }
            errors_dict[rr.rule_id] = {
                "dimension": rr.dimension,
                "reason": rr.error_summary,
                "positive_error": rr.positive_case.error if rr.positive_case else None,
                "negative_error": rr.negative_case.error if rr.negative_case else None,
            }
            error_count += 1
            continue

        # 正常路径
        rules_dict[rr.rule_id] = {
            "dimension": rr.dimension,
            "status": "ok",
            "TP": rr.TP, "FP": rr.FP, "FN": rr.FN, "TN": rr.TN,
            "precision": round(rr.precision, 4),
            "recall": round(rr.recall, 4),
            "positive_case": _case_to_dict(rr.positive_case),
            "negative_case": _case_to_dict(rr.negative_case),
        }
        if rr.TP + rr.FP > 0:
            p_list.append(rr.precision)
        if rr.TP + rr.FN > 0:
            r_list.append(rr.recall)
        ok_count += 1

    macro_p = sum(p_list) / len(p_list) if p_list else 0.0
    macro_r = sum(r_list) / len(r_list) if r_list else 0.0
    results = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rules": rules_dict,
        "summary": {
            "rule_count": len(rule_results),
            "ok_count": ok_count,
            "error_count": error_count,
            "macro_precision": round(macro_p, 4),
            "macro_recall": round(macro_r, 4),
            "macro_note": "macro 仅基于 status=ok 的规则, error 规则被排除以防污染",
        },
    }
    errors = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "error_count": error_count,
        "errors": errors_dict,
    }
    return results, errors


def _case_to_dict(case: Optional[RuleCaseResult]) -> Optional[Dict[str, Any]]:
    if case is None:
        return None
    d = asdict(case)
    # matched_finding 太大 (含完整 worker output), 只留 rule_id + issue + location
    if d.get("matched_finding"):
        m = d["matched_finding"]
        d["matched_finding"] = {
            "rule_id": m.get("rule_id"),
            "issue": (m.get("issue") or "")[:200],
            "location": m.get("location"),
            "severity": m.get("severity"),
        }
    return d


def print_report(results: Dict[str, Any], regression_info: Optional[Dict[str, Any]] = None):
    """友好 stdout 报告"""
    print("\n" + "=" * 70)
    print(f"啄木鸟 Rule Regression Report  ({results['timestamp']})")
    print(f"  schema_version={results.get('schema_version', '<v1>')}")
    print("=" * 70)
    summ = results["summary"]
    print(f"\n规则数: {summ['rule_count']} "
          f"(ok={summ.get('ok_count', '-')}, error={summ.get('error_count', '-')})  "
          f"Macro-P: {summ['macro_precision']:.3f}  "
          f"Macro-R: {summ['macro_recall']:.3f}")
    if summ.get("error_count"):
        print(f"  ⚠ 有 {summ['error_count']} 条规则 worker 调用失败, 已排除出 macro")
    print()

    print(f"{'rule_id':<10} {'dim':<14} {'P':>6} {'R':>6} "
          f"{'TP':>3} {'FP':>3} {'FN':>3} {'TN':>3}  status")
    print("-" * 70)
    for rid, r in results["rules"].items():
        status_parts = []
        if r.get("status") == "error":
            status_parts.append("ERROR")
        if r["positive_case"] and r["positive_case"].get("error"):
            status_parts.append("POS_ERR")
        if r["negative_case"] and r["negative_case"].get("error"):
            status_parts.append("NEG_ERR")
        if r["positive_case"] and r["positive_case"].get("evidence_aligned") is False:
            status_parts.append("NLI_MISALIGNED")
        status = " ".join(status_parts) or "ok"
        # P/R 可能是 None (error 规则)
        p_str = f"{r['precision']:>6.2f}" if r.get("precision") is not None else "  N/A "
        r_str = f"{r['recall']:>6.2f}" if r.get("recall") is not None else "  N/A "
        print(f"{rid:<10} {r['dimension']:<14} "
              f"{p_str} {r_str} "
              f"{r['TP']:>3} {r['FP']:>3} {r['FN']:>3} {r['TN']:>3}  {status}")

    if regression_info:
        print("\n" + "-" * 70)
        if regression_info["regression"]:
            print(f"REGRESSION DETECTED (tolerance={regression_info['tolerance']:.2%})")
            for issue in regression_info["issues"]:
                print(f"  - {issue}")
        else:
            print(f"No regression vs baseline (tolerance={regression_info['tolerance']:.2%})")
        infra = regression_info.get("infra_errors") or []
        if infra:
            print(f"\n基础设施告警 ({len(infra)} 条规则 worker 失败, 跳过对比):")
            for it in infra:
                print(f"  - {it}")
    print()


# ============================================================
# 回归 gate
# ============================================================

def compare_to_baseline(
    current: Dict[str, Any],
    baseline: Dict[str, Any],
    tolerance: float,
) -> Dict[str, Any]:
    """对比当前结果与 baseline, 返回 regression info dict.

    跳过策略:
    - baseline 中 status=error 的规则不进对比 (没真实信号)
    - 当前 status=error 的规则视为"基础设施故障", 不报 regression, 单独记 infra_errors
    """
    issues: List[str] = []
    infra_errors: List[str] = []
    cur_rules = current.get("rules", {})
    base_rules = baseline.get("rules", {})

    for rid, base in base_rules.items():
        # baseline 当时是 error → 没基线可比
        if base.get("status") == "error":
            continue
        cur = cur_rules.get(rid)
        if cur is None:
            issues.append(f"{rid}: 当前结果缺失 (baseline 有)")
            continue
        # 当前是 error → 基础设施故障, 不算 regression 但要冒泡
        if cur.get("status") == "error":
            infra_errors.append(f"{rid}: 当前 worker 调用失败, 跳过对比")
            continue
        # 旧 baseline 可能没 precision 字段 (理论上不会到这, 防御)
        if base.get("precision") is None or cur.get("precision") is None:
            continue
        dp = base["precision"] - cur["precision"]
        dr = base["recall"] - cur["recall"]
        if dp > tolerance:
            issues.append(
                f"{rid}: precision 降 {dp:.2%} "
                f"(baseline {base['precision']:.2f} → 当前 {cur['precision']:.2f})"
            )
        if dr > tolerance:
            issues.append(
                f"{rid}: recall 降 {dr:.2%} "
                f"(baseline {base['recall']:.2f} → 当前 {cur['recall']:.2f})"
            )

    return {
        "regression": len(issues) > 0,
        "issues": issues,
        "infra_errors": infra_errors,
        "tolerance": tolerance,
    }


# ============================================================
# CLI 主入口
# ============================================================

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="啄木鸟 Rule Regression Harness")
    parser.add_argument(
        "--rules-yaml",
        default=os.path.join(_ROOT, "workspace", "review-rules", "review-checklist.yaml"),
        help="规则 yaml 路径 (默认 workspace/review-rules/review-checklist.yaml)",
    )
    parser.add_argument(
        "--baseline",
        default=os.path.join(_HERE, "fixtures", "regression_baseline.json"),
        help="baseline.json 路径",
    )
    parser.add_argument("--update-baseline", action="store_true",
                        help="把当前结果写回 baseline.json")
    parser.add_argument("--tolerance", type=float, default=0.05,
                        help="P/R 下降容忍阈值 (绝对差异, 默认 0.05)")
    parser.add_argument("--output", default=os.path.join(_HERE, "fixtures", "regression_results.json"),
                        help="results.json 输出路径")
    parser.add_argument("--skip-nli", action="store_true",
                        help="跳过二层 NLI 校验, 加速 dev")
    parser.add_argument("--rule-id", help="只跑指定规则 (调试用)")
    parser.add_argument("--dry-run", action="store_true",
                        help="只验证 yaml 加载, 不调 LLM (默认 TP/TN 通过)")
    args = parser.parse_args(argv)

    # ---------- 加载规则 ----------
    try:
        rules = load_rules_with_examples(args.rules_yaml)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.rule_id:
        rules = [r for r in rules if r["id"] == args.rule_id]
        if not rules:
            print(f"ERROR: 没找到规则 {args.rule_id}", file=sys.stderr)
            return 2

    if not rules:
        print("ERROR: 没有可跑的规则 (yaml 中没找到带 positive_example 的条目)", file=sys.stderr)
        return 2

    # ---------- 加载 dim 反查 ----------
    rule_to_dim = build_rule_to_dimension_map()

    # ---------- 跑规则 ----------
    rule_results: List[RuleResult] = []
    for rule in rules:
        rid = rule["id"]
        dim_key = rule_to_dim.get(rid)
        if not dim_key:
            log.warning(f"规则 {rid} 在 review-dimensions.yaml 中没找到 owner, 跳过")
            continue
        log.info(f"=== 评估规则 {rid} (维度: {dim_key}) ===")
        try:
            result = evaluate_rule(rule, dim_key, skip_nli=args.skip_nli, dry_run=args.dry_run)
            rule_results.append(result)
        except Exception as e:
            log.error(f"{rid} 评估异常: {e}\n{traceback.format_exc()}")
            # 异常仍记一条 (TP/FP/FN/TN 全 0), 不阻断后续规则
            rr = RuleResult(rule_id=rid, dimension=dim_key)
            rule_results.append(rr)

    # ---------- 序列化 + 写 results + errors ----------
    results, errors = serialize_results(rule_results)
    out_dir = os.path.dirname(args.output)
    if out_dir:  # 修: 当 --output 是当前目录的相对文件名时 dirname 为空, 跳过 makedirs
        os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log.info(f"results 已写到: {args.output}")

    # 同步写 errors.json (与 results 同目录, 文件名添加 _errors 后缀)
    if args.output.endswith(".json"):
        errors_path = args.output[:-5] + "_errors.json"
    else:
        errors_path = args.output + "_errors.json"
    with open(errors_path, "w", encoding="utf-8") as f:
        json.dump(errors, f, ensure_ascii=False, indent=2)
    log.info(f"errors 已写到: {errors_path}")

    # ---------- 回归 gate ----------
    regression_info: Optional[Dict[str, Any]] = None
    baseline_exists = os.path.exists(args.baseline)

    # baseline schema 校验: v1 (无 schema_version) 自动作废
    baseline_outdated = False
    if baseline_exists:
        try:
            with open(args.baseline, "r", encoding="utf-8") as f:
                baseline = json.load(f)
            base_ver = baseline.get("schema_version")
            if base_ver != BASELINE_SCHEMA_VERSION:
                print(f"[schema-mismatch] baseline schema_version={base_ver} "
                      f"!= 当前 {BASELINE_SCHEMA_VERSION}, 视为作废需重建 (--update-baseline)")
                baseline_outdated = True
        except (OSError, json.JSONDecodeError) as e:
            print(f"[baseline-load-fail] {e}, 视为不存在")
            baseline_exists = False

    # baseline 同时写一份 errors (跟 results 错位文件保持一致)
    baseline_errors_path = args.baseline[:-5] + "_errors.json" if args.baseline.endswith(".json") \
        else args.baseline + "_errors.json"

    if args.update_baseline:
        os.makedirs(os.path.dirname(args.baseline), exist_ok=True)
        with open(args.baseline, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        with open(baseline_errors_path, "w", encoding="utf-8") as f:
            json.dump(errors, f, ensure_ascii=False, indent=2)
        print(f"[update-baseline] 已写入 {args.baseline}")
        print(f"[update-baseline] errors 写入 {baseline_errors_path}")
    elif not baseline_exists or baseline_outdated:
        # 第一次跑或 schema 作废, 直接当 baseline
        os.makedirs(os.path.dirname(args.baseline), exist_ok=True)
        with open(args.baseline, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        with open(baseline_errors_path, "w", encoding="utf-8") as f:
            json.dump(errors, f, ensure_ascii=False, indent=2)
        why = "schema 作废" if baseline_outdated else "baseline 不存在"
        print(f"[first-run] {why}, 当前结果已 promote 为 baseline ({args.baseline})")
    else:
        regression_info = compare_to_baseline(results, baseline, args.tolerance)

    # ---------- 打印报告 ----------
    print_report(results, regression_info)

    if regression_info and regression_info["regression"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
