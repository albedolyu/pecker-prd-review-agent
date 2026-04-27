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

    # ClickHouse 持久化 (目前只 log)
    _persist_to_clickhouse({
        "route_id": route_id,
        "vendor": vendor,
        "model": model,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "p_score": capability["p"],
        "r_score": capability["r"],
        "f1": capability["f1"],
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
    """真跑 LLM (P0 不会进, 留 P1 真评测时填). 返回 (resp, error_type, fallback_triggered).

    NOTE: P0 阶段 dry_run=True 默认, 这条代码路径不应被触发. 留下让 runner 形态
    完整即可。真跑评测见 Wave 4 plan.
    """
    raise NotImplementedError(
        f"非 dry_run 模式真跑 LLM 留待 Wave 4. 当前 P0 只支持 --dry-run."
    )


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
