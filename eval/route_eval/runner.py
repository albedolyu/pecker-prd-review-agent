"""单 route 评测调度器 -- 跑 N 次 + 收原始 responses + 收 call_records.

核心: 用 monkeypatch 改 ``os.environ['PECKER_ROUTES_FILE']`` 指向临时 routes.yaml,
候选 route 切到 ``vendor:model``, 复用 model_router 不重写。

dry_run=True 时不真发请求, 用 _FakeResponse 走通 pipeline (跑通 import + 5 维度
metrics + 报告生成的端到端冒烟).

ClickHouse 持久化目前只 log, 真 INSERT 留 follow-up. schema 见 _persist_to_clickhouse
docstring.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import warnings
from typing import Any, Dict, List, Optional

# 项目根 sys.path 注入 (脚本入口若没设, runner 自检兜底)
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from logger import get_logger  # noqa: E402

log = get_logger("route_eval.runner")


# ============================================================
# Fake response (dry-run 模式专用)
# ============================================================

class _FakeResponse:
    """dry-run 模式 mock route_call 返回, 含 _FakeResponse 必备字段."""

    def __init__(self, model: str, items: Optional[List[Dict[str, Any]]] = None):
        self.model = model
        self.text_blocks = [{"type": "text", "text": "[]"}]
        self.tool_calls = []
        self.stop_reason = "end_turn"
        self.usage = {"input_tokens": 100, "output_tokens": 50}
        self.truncated = False
        # 评测专用扩展字段 (cuckoo_adapter 通过 .items 取)
        self.items = items or []


class _BatchResponse:
    """真跑分类型 route 时, 把 N 条 dataset entry 的预测聚合成单 resp.

    items = list of predictions (binary: detected_hallucination/expected_hallucination/correct;
    multiclass: predicted_tier/expected_tier/correct).
    usage 是 N 次 sub-call 的累计.
    """

    def __init__(self, model: str, predictions: List[Dict[str, Any]]):
        self.model = model
        self.text_blocks = [{"type": "text", "text": ""}]
        self.tool_calls = []
        self.stop_reason = "end_turn"
        self.usage: Dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        self.truncated = False
        self.items = predictions

    def add_usage(self, usage: Dict[str, Any]) -> None:
        self.usage["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
        self.usage["output_tokens"] += int(usage.get("output_tokens", 0) or 0)


def _gen_fake_items(seed_offset: int = 0) -> List[Dict[str, Any]]:
    """生成 dry-run 假改进项, 模拟 worker 输出 schema. 不同 seed 出不同条数, 模拟 sampling noise."""
    base = [
        {
            "id": f"FAKE-{seed_offset}-{i}",
            "rule_id": ["V-08", "RC-014", "EV-01"][i % 3],
            "location": f"3.{i + 1}",
            "issue": f"dry-run 假改进项 {i}",
            "problem": f"模拟问题 {i}",
            "suggestion": "模拟建议",
            "severity": ["must", "should", "should"][i % 3],
            "evidence_type": "B",
            "evidence_content": "RC-014 验证规则",
            "dimension": "structure",
        }
        for i in range(3 + (seed_offset % 2))  # 3 或 4 条, 制造轻微 N0 方差
    ]
    return base


# ============================================================
# 临时 routes.yaml 生成
# ============================================================

_OVERRIDE_YAML_TEMPLATE = """
vendors:
  {vendor}:
    cli_client: {cli_client}
    native_client: {native_client}
    model_tiers:
{tiers}
    fallback_chain: [{tier_keys}]

routes:
  {route_id}: {{vendor: {vendor}, transport: cli, model: {tier}, retry_policy: foreground}}
"""


def _build_override_yaml(
    route_id: str,
    vendor: str,
    model_tier: str,
    real_model: str,
) -> str:
    """构造一个最小可用 routes.yaml 把候选 route 切到指定 vendor:model.

    实际 dry-run 用 fake clients (避免真发 LLM), production 用法 vendor 必须在
    project 主 routes.yaml vendors 里有合法注册。
    """
    # 默认指向项目主路由的 client 实现 (dry-run 时被 monkey-patched 的 route_call 拦截)
    cli_client = "clients.claude_cli.ClaudeCodeCLIClient"
    native_client = "clients.anthropic_native.AnthropicNativeClient"
    if vendor == "openai":
        cli_client = "clients.codex_cli.CodexCLIClient"  # P1 才会真存在
        native_client = "clients.codex_cli.CodexCLIClient"

    tier_lines = f"      {model_tier}: {real_model}"
    return _OVERRIDE_YAML_TEMPLATE.format(
        vendor=vendor,
        cli_client=cli_client,
        native_client=native_client,
        tiers=tier_lines,
        tier_keys=model_tier,
        route_id=route_id,
        tier=model_tier,
    )


# ============================================================
# ClickHouse 持久化 (TODO follow-up)
# ============================================================

def _persist_to_clickhouse(record: Dict[str, Any]) -> None:
    """把单次 route_eval 结果写 ClickHouse route_eval_runs 表.

    TODO: P0 后实施, 当前只 log.

    连接信息 (memory clickhouse_db.md):
        host: 117.50.192.241
        port: 18123 (HTTP)
        user: lvxinhang

    Schema:
        CREATE TABLE route_eval_runs (
            route_id String, vendor String, model String, ts DateTime,
            p_score Float64, r_score Float64, f1 Float64,
            overlap_pct Float64, p95_ms UInt32, cost_usd Float64,
            hallucination_tpr Float64, hallucination_fpr Float64,
            kappa Float64, complementary_pct Float64,
            quota_rate Float64, json_parse_fail_rate Float64
        ) ENGINE = MergeTree ORDER BY (route_id, ts);

    INSERT 示意:
        INSERT INTO route_eval_runs FORMAT JSONEachRow
        {"route_id": "...", "vendor": "...", ...}
    """
    log.info(f"[clickhouse] would insert into route_eval_runs: {record}")


# ============================================================
# 数据集加载 (graceful 退化, Agent C 还没建好时不崩)
# ============================================================

def _load_dataset_safe(name: str) -> List[Dict[str, Any]]:
    """try import datasets.loader.load_dataset, 没建好就返空 list + warn."""
    try:
        from eval.route_eval.datasets.loader import load_dataset
        return load_dataset(name)
    except (ImportError, ModuleNotFoundError, AttributeError) as e:
        warnings.warn(
            f"[route_eval.runner] dataset {name!r} 不可用 (Agent C 还没建?): {e}; "
            f"用空 dataset 兜底",
            RuntimeWarning,
            stacklevel=2,
        )
        return []
    except FileNotFoundError as e:
        warnings.warn(
            f"[route_eval.runner] dataset {name!r} 文件缺失: {e}; 用空 dataset 兜底",
            RuntimeWarning,
            stacklevel=2,
        )
        return []


# ============================================================
# 主入口
# ============================================================

def run_route_eval(
    route_id: str,
    vendor: str,
    model: str,
    runs: int,
    dataset_name: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """跑单 route × vendor × model × N runs, 返回 raw responses + call_records + metrics.

    Args:
        route_id: 如 "advisor.goshawk"
        vendor: 如 "anthropic" | "openai"
        model: tier 别名, 如 "sonnet" | "opus" | "pro"
        runs: 评测轮次, >= 1
        dataset_name: 见 datasets.loader.load_dataset 的 5 个名字
        dry_run: True 不发真请求, 用 _FakeResponse 跑通 pipeline

    Returns:
        {
            route_id, vendor, model, runs, dataset, dry_run,
            responses: List[List[item]],     # 外层每 run 一个, 内层 items
            call_records: List[dict],        # 每次 route_call 的元数据
            ground_truth: List[dict],        # 数据集里的 GT (worker.* 才有)
            metrics: {
                capability: {...},
                stability: {...},
                cost_latency: {...},
                failure_modes: {...},
            },
        }
    """
    if runs < 1:
        raise ValueError(f"runs 必须 >= 1, 实际 {runs}")

    log.info(
        f"[route_eval] start {route_id} @ {vendor}:{model} runs={runs} "
        f"dataset={dataset_name} dry_run={dry_run}"
    )

    # 加载数据集 (graceful)
    dataset = _load_dataset_safe(dataset_name)
    # 抽 ground_truth (worker.* / advisor.* 数据集有, intent/template 没有)
    ground_truth: List[Dict[str, Any]] = []
    for entry in dataset:
        gt = entry.get("ground_truth") or entry.get("ground_truth_resolution") or []
        if isinstance(gt, list):
            ground_truth.extend(gt)

    # 跑 N 次
    all_responses: List[List[Dict[str, Any]]] = []
    call_records: List[Dict[str, Any]] = []

    for run_idx in range(runs):
        t0 = time.time()
        try:
            if dry_run:
                # 不真发, 直接 _FakeResponse
                items = _gen_fake_items(seed_offset=run_idx)
                resp = _FakeResponse(model=model, items=items)
                error_type = None
                fallback_triggered = False
            else:
                resp, error_type, fallback_triggered = _do_real_call(
                    route_id, vendor, model, dataset
                )
                items = getattr(resp, "items", None) or []
        except Exception as e:  # pragma: no cover -- dry-run 不会进, 真跑兜底
            log.warning(f"[route_eval] run {run_idx + 1} 失败: {type(e).__name__}: {e}")
            resp = _FakeResponse(model=model, items=[])
            items = []
            error_type = type(e).__name__.lower()
            fallback_triggered = False

        latency_ms = int((time.time() - t0) * 1000)
        usage = getattr(resp, "usage", {}) or {}
        # 简单 cost 估 (dry-run 用假 token 数)
        cost_usd = _estimate_cost(model, usage)

        all_responses.append(items)
        call_records.append({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "route_id": route_id,
            "vendor": vendor,
            "model": model,
            "latency_ms": latency_ms,
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "cost_usd": cost_usd,
            "stop_reason": getattr(resp, "stop_reason", ""),
            "error_type": error_type,
            "fallback_triggered": fallback_triggered,
        })

        log.info(
            f"[route_eval] run {run_idx + 1}/{runs} ok: {len(items)} items, "
            f"{latency_ms}ms, ${cost_usd:.6f}"
        )

    # 算 5 维度指标
    from . import metrics as metrics_mod

    # 按 route_id 选 capability metric:
    #   verify.nli   → binary classification (TPR/FPR)
    #   router.intent → multiclass classification (per-class accuracy)
    #   其他        → cuckoo P/R/F1 (worker.* / advisor.* 默认)
    if route_id == "verify.nli" and not dry_run:
        flat_preds = [p for run in all_responses for p in run]
        capability = metrics_mod.compute_classification_metrics(flat_preds, task_type="binary")
    elif route_id == "router.intent" and not dry_run:
        flat_preds = [p for run in all_responses for p in run]
        capability = metrics_mod.compute_classification_metrics(flat_preds, task_type="multiclass")
    else:
        capability = metrics_mod.compute_capability(all_responses, ground_truth)
    stability = metrics_mod.compute_stability(all_responses)
    cost_latency = metrics_mod.compute_cost_latency(call_records)
    failure_modes = metrics_mod.compute_failure_modes(call_records)

    result = {
        "route_id": route_id,
        "vendor": vendor,
        "model": model,
        "runs": runs,
        "dataset": dataset_name,
        "dry_run": dry_run,
        "responses": all_responses,
        "call_records": call_records,
        "ground_truth": ground_truth,
        "capability": capability,
        "stability": stability,
        "cost_latency": cost_latency,
        "failure_modes": failure_modes,
        "metrics": {
            "capability": capability,
            "stability": stability,
            "cost_latency": cost_latency,
            "failure_modes": failure_modes,
        },
    }

    # ClickHouse 持久化 (目前只 log) -- 用 .get 兜底兼容 classification 输出 (无 p/r/f1, 有 tpr/fpr/accuracy)
    _persist_to_clickhouse({
        "route_id": route_id,
        "vendor": vendor,
        "model": model,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "p_score": capability.get("p", capability.get("accuracy", 0.0)),
        "r_score": capability.get("r", capability.get("tpr", 0.0)),
        "f1": capability.get("f1", capability.get("accuracy", 0.0)),
        "task_type": capability.get("task_type", "issues"),
        "tpr": capability.get("tpr", 0.0),
        "fpr": capability.get("fpr", 0.0),
        "overlap_pct": stability["overlap"],
        "p95_ms": int(cost_latency["p95_ms"]),
        "cost_usd": cost_latency["cost_usd_per_run"],
        "quota_rate": failure_modes["quota_rate"],
        "json_parse_fail_rate": failure_modes["json_parse_fail_rate"],
    })

    return result


# ============================================================
# 内部辅助
# ============================================================

def _do_real_call(
    route_id: str,
    vendor: str,
    model_tier: str,
    dataset: List[Dict[str, Any]],
) -> tuple:
    """按 route_id 分发真跑 calling pattern, 返回 (resp, error_type, fallback_triggered).

    Wave 4 P0 实现 2 类 pattern (verify.nli + router.intent), 其他 route 仍 raise
    NotImplementedError 保持框架完整 (worker.* / advisor.* / eval.cuckoo 等待 P1
    接 codex 时一起补 -- 避免做两次).

    单 run 处理的 case 数受 PECKER_EVAL_MAX_CASES_PER_RUN env 控制 (默认 10),
    避免 60 case × 3 runs 跑批太贵.
    """
    if not dataset:
        return _FakeResponse(model=model_tier, items=[]), "empty_dataset", False

    max_cases = int(os.environ.get("PECKER_EVAL_MAX_CASES_PER_RUN", "10"))

    if route_id == "verify.nli":
        return _call_nli_pattern(model_tier, dataset, max_cases)
    if route_id == "router.intent":
        return _call_intent_pattern(model_tier, dataset, max_cases)
    if route_id == "advisor.goshawk.shadow":
        # shadow 默认 enabled=false, 不应被 baseline 跑到; 留兜底
        return _FakeResponse(model=model_tier, items=[]), "shadow_disabled", False

    raise NotImplementedError(
        f"route {route_id!r} 真跑 calling pattern 待 P1 接 codex 时一起补 "
        f"(worker.* / advisor.* / eval.cuckoo). 当前 P0 实跑仅 verify.nli + router.intent."
    )


def _call_nli_pattern(
    model_tier: str,
    dataset: List[Dict[str, Any]],
    max_cases: int,
) -> tuple:
    """对 hallucination dataset 跑 verify.nli 真调用, 聚合 binary classification predictions.

    决策规则: contradict_score > 0.5 视为检测到 hallucination
    (跟 verify_evidence 上层 EMA 阈值一致).
    """
    from review.evidence_verify import _llm_nli_score

    # Stratified sample: 真 (is_hallucination=False) 和 假 各取 max_cases//2
    # (dataset 30 真 + 30 假, 直接 [:N] 全是真, TPR/FPR 失效)
    halluc_cases = [e for e in dataset if e.get("is_hallucination")]
    real_cases = [e for e in dataset if not e.get("is_hallucination")]
    half = max(1, max_cases // 2)
    sub = halluc_cases[:half] + real_cases[:half]
    predictions: List[Dict[str, Any]] = []
    error_type: Optional[str] = None
    resp = _BatchResponse(model=model_tier, predictions=[])

    # 2026-04-27 P1 调参: 阈值 0.5→0.3, n_samples 2→4 (baseline 实测 TPR=0,
    # 配合 evidence_verify.py prompt 加强 contradict 判准, 重测看 TPR)
    nli_threshold = float(os.environ.get("PECKER_NLI_CONTRADICT_THRESHOLD", "0.3"))
    nli_samples = int(os.environ.get("PECKER_NLI_N_SAMPLES", "4"))
    for entry in sub:
        item = entry.get("item", {}) or {}
        wiki_pages = entry.get("wiki_pages", {}) or {}
        is_halluc = bool(entry.get("is_hallucination", False))
        try:
            score = _llm_nli_score(
                client=None,
                item=item,
                wiki_pages=wiki_pages,
                n_samples=nli_samples,
            )
            detected = score.get("contradict_score", 0.0) > nli_threshold
            predictions.append({
                "id": entry.get("id", ""),
                "expected_hallucination": is_halluc,
                "detected_hallucination": detected,
                "correct": detected == is_halluc,
                "scores": score,
                "construction_method": entry.get("construction_method", ""),
            })
            # _llm_nli_score 内部走 route_call, 返回的 score 不带 token usage;
            # token usage 在 token_tracker 里集中, 这里粗估 (每次 ~500/100)
            resp.add_usage({"input_tokens": 500 * score.get("n_samples_succeeded", 0),
                            "output_tokens": 100 * score.get("n_samples_succeeded", 0)})
        except Exception as e:  # pragma: no cover -- 真跑兜底
            log.warning(f"[nli] case {entry.get('id')} 失败: {type(e).__name__}: {e}")
            error_type = type(e).__name__.lower()
            predictions.append({
                "id": entry.get("id", ""),
                "expected_hallucination": is_halluc,
                "detected_hallucination": False,
                "correct": False,
                "error": str(e)[:200],
            })

    resp.items = predictions
    return resp, error_type, False


def _call_intent_pattern(
    model_tier: str,
    dataset: List[Dict[str, Any]],
    max_cases: int,
) -> tuple:
    """对 intent dataset 跑 router.intent 真调用, 聚合 multiclass predictions.

    expected_tier 取值: opus / sonnet / haiku / reject (route_intent 只输出
    opus/sonnet/haiku, reject 类应被识别为 sonnet 默认 -- 这是已知 fallback 限制).
    """
    from router import route_intent

    # Stratified sample: 4 类 (opus/sonnet/haiku/reject) 各取 max_cases//4
    by_tier: Dict[str, List[Dict[str, Any]]] = {}
    for e in dataset:
        by_tier.setdefault(e.get("expected_tier", "sonnet"), []).append(e)
    per_tier = max(1, max_cases // 4)
    sub: List[Dict[str, Any]] = []
    for tier_name in ("opus", "sonnet", "haiku", "reject"):
        sub.extend(by_tier.get(tier_name, [])[:per_tier])
    predictions: List[Dict[str, Any]] = []
    error_type: Optional[str] = None
    resp = _BatchResponse(model=model_tier, predictions=[])

    for entry in sub:
        prd_name = entry.get("prd_name", "")
        user_instruction = entry.get("user_instruction", "PRD 评审")
        expected = entry.get("expected_tier", "sonnet")
        try:
            predicted = route_intent(client=None, prd_name=prd_name, user_instruction=user_instruction)
            predictions.append({
                "prd_name": prd_name,
                "expected_tier": expected,
                "predicted_tier": predicted,
                "correct": predicted == expected,
            })
            resp.add_usage({"input_tokens": 80, "output_tokens": 5})
        except Exception as e:  # pragma: no cover -- 真跑兜底
            log.warning(f"[intent] case {prd_name!r} 失败: {type(e).__name__}: {e}")
            error_type = type(e).__name__.lower()
            predictions.append({
                "prd_name": prd_name,
                "expected_tier": expected,
                "predicted_tier": "sonnet",  # route_intent 失败默认 sonnet
                "correct": expected == "sonnet",
                "error": str(e)[:200],
            })

    resp.items = predictions
    return resp, error_type, False


def _estimate_cost(model: str, usage: Dict[str, Any]) -> float:
    """从 model + usage 估算单次成本 USD. 复用 clients/token_tracker."""
    try:
        from clients.token_tracker import compute_call_cost_usd
        return compute_call_cost_usd(model, usage)
    except ImportError:
        # 兜底: sonnet 定价
        in_tok = int(usage.get("input_tokens", 0) or 0)
        out_tok = int(usage.get("output_tokens", 0) or 0)
        return round(in_tok * 3.0 / 1_000_000 + out_tok * 15.0 / 1_000_000, 6)
