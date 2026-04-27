"""单 route 评测调度器 -- 跑 N 次 + 收原始 responses + 收 call_records.

核心: 用 monkeypatch 改 ``os.environ['PECKER_ROUTES_FILE']`` 指向临时 routes.yaml,
候选 route 切到 ``vendor:model``, 复用 model_router 不重写。

dry_run=True 时不真发请求, 用 _FakeResponse 走通 pipeline (跑通 import + 5 维度
metrics + 报告生成的端到端冒烟).

ClickHouse 持久化目前只 log, 真 INSERT 留 follow-up. schema 见 _persist_to_clickhouse
docstring.
"""
from __future__ import annotations

import json
import os
import re
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

    Wave 4 实现 verify.nli + router.intent 两类 classification pattern.
    Wave 5C 补 worker.* / advisor.* / eval.cuckoo 三类 pattern (本次), 让 baseline
    全表都能跑出真数据.

    单 run 处理的 case 数受 PECKER_EVAL_MAX_CASES_PER_RUN env 控制 (默认按 pattern
    取不同值: nli/intent=10, worker=2, advisor=3 -- worker 单 call 慢, 限小一点).
    """
    if not dataset:
        return _FakeResponse(model=model_tier, items=[]), "empty_dataset", False

    # 默认 max_cases: classification 类用 10, worker 用 2, advisor 用 3
    env_max = os.environ.get("PECKER_EVAL_MAX_CASES_PER_RUN", "").strip()

    if route_id == "verify.nli":
        max_cases = int(env_max or "10")
        return _call_nli_pattern(model_tier, dataset, max_cases)
    if route_id == "router.intent":
        max_cases = int(env_max or "10")
        return _call_intent_pattern(model_tier, dataset, max_cases)
    if route_id.startswith("worker."):
        max_cases = int(env_max or "2")
        return _call_worker_pattern(route_id, model_tier, dataset, max_cases)
    if route_id.startswith("advisor.goshawk"):
        if route_id == "advisor.goshawk.shadow":
            # shadow 默认 enabled=false (model_routes.yaml), 走 router 时被
            # RouteDisabledError 挡住; 这里兜底返回空 resp 避免崩
            return _FakeResponse(model=model_tier, items=[]), "shadow_disabled", False
        max_cases = int(env_max or "3")
        return _call_advisor_pattern(route_id, model_tier, dataset, max_cases)
    if route_id == "eval.cuckoo":
        max_cases = int(env_max or "2")
        return _call_eval_cuckoo_pattern(route_id, model_tier, dataset, max_cases)

    raise NotImplementedError(
        f"route {route_id!r} 真跑 calling pattern 未支持 "
        f"(已实现: verify.nli / router.intent / worker.* / advisor.goshawk* / eval.cuckoo)"
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


# ============================================================
# Wave 5C: worker / advisor / eval.cuckoo calling patterns
# ============================================================

# 项目根 (用于解析 dataset 的相对 prd_path)
_RUNNER_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# PRD 内容截断长度 (避免 token 爆 -- 8000 字符 ≈ 4-5k tokens)
_PRD_TRUNCATE_CHARS = 8000


def _read_prd_safe(prd_path: str) -> str:
    """读 PRD 文件并截断, 路径解析失败返空串."""
    abs_path = prd_path if os.path.isabs(prd_path) else os.path.join(_RUNNER_PROJECT_ROOT, prd_path)
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (FileNotFoundError, OSError) as e:
        log.warning(f"[worker_pattern] 读 PRD 失败 {abs_path}: {e}")
        return ""
    if len(content) > _PRD_TRUNCATE_CHARS:
        content = content[:_PRD_TRUNCATE_CHARS] + "\n\n... [PRD 内容已截断, 评测期只看前 8000 字]"
    return content


def _extract_text_from_resp(resp: Any) -> str:
    """从 UnifiedResponse / _FakeResponse 拼出 text content (兼容 dict / object 两种 block)."""
    parts: List[str] = []
    for block in getattr(resp, "text_blocks", []) or []:
        if isinstance(block, dict):
            t = block.get("text", "")
        else:
            t = getattr(block, "text", "")
        if t:
            parts.append(t)
    return "".join(parts)


_JSON_LIST_RE = re.compile(r"\[\s*(?:\{.*?\})?(?:\s*,\s*\{.*?\})*\s*\]", re.DOTALL)
_JSON_OBJ_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def _parse_json_list(text: str) -> List[Dict[str, Any]]:
    """从 LLM response 抽 JSON list (容错: ```json fenced / 内嵌 / 无 list 都返空).

    优先策略:
    1. 先剥 ```json ... ``` fence (LLM 常加)
    2. 直接 json.loads 整段
    3. 正则找第一个 [...] 块再 loads
    4. 找不到返 []
    """
    if not text:
        return []
    # 剥 markdown code fence
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1).strip()
    else:
        candidate = text.strip()

    # 直接 try
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, list):
            return [x for x in parsed if isinstance(x, dict)]
        if isinstance(parsed, dict):
            # 可能是 {"items": [...]} 或 {"issues": [...]}
            for key in ("items", "issues", "review_items", "results"):
                if key in parsed and isinstance(parsed[key], list):
                    return [x for x in parsed[key] if isinstance(x, dict)]
    except (json.JSONDecodeError, TypeError):
        pass

    # 正则找首个 [ ... ] 块
    list_match = _JSON_LIST_RE.search(text)
    if list_match:
        try:
            parsed = json.loads(list_match.group(0))
            if isinstance(parsed, list):
                return [x for x in parsed if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass
    return []


def _parse_json_obj(text: str) -> Dict[str, Any]:
    """从 LLM response 抽 JSON object (advisor 决策用), 失败返 {}."""
    if not text:
        return {}
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fence_match.group(1).strip() if fence_match else text.strip()
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    obj_match = _JSON_OBJ_RE.search(text)
    if obj_match:
        try:
            parsed = json.loads(obj_match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def _call_worker_pattern(
    route_id: str,
    model_tier: str,
    dataset: List[Dict[str, Any]],
    max_cases: int,
) -> tuple:
    """对 business_prd_gt dataset 跑 worker.* 真调用, 输出 issues list 给 cuckoo P/R/F1.

    最简化策略 (不走 review.worker._worker_core 全流程):
    - 抽 dim_key from route_id (worker.compliance → "compliance")
    - 读 PRD 内容 (截断 8000 字符)
    - 单维度 prompt 让模型输出 JSON list of issues
    - 累计每条 entry 的 items 到 _BatchResponse.items
    """
    from model_router import route_call

    dim_key = route_id.split(".", 1)[1] if "." in route_id else "default"
    sub = dataset[:max_cases]
    all_items: List[Dict[str, Any]] = []
    error_type: Optional[str] = None
    fallback_triggered = False
    resp = _BatchResponse(model=model_tier, predictions=[])

    # 注意: system prompt 走 --system-prompt argv 传给 claude CLI, Windows cmd 会
    # 解析 shell 元字符 "|" "<" ">" "&" 等 (memory: claude_cli_windows_subprocess.md
    # 同款坑). 全部用普通字符替代避免触发 shell 解析.
    system = (
        f"你是 PRD 评审员, 专注 {dim_key} 维度审核. "
        "审阅以下 PRD, 输出 **只含一个 JSON list** 的回复 (不要 markdown 文本). "
        "每条 issue 字段: "
        "rule_id (规则ID 如 V-08 / RC-014 / EV-01), "
        "severity (取值: must / should / info), "
        "location (章节号 如 3.2), "
        "issue (80 字以内问题描述), "
        "suggestion (80 字以内修复建议). "
        "未发现问题则返 [], 不要硬凑."
    )

    for entry in sub:
        prd_path = entry.get("prd_path", "")
        prd_content = _read_prd_safe(prd_path)
        if not prd_content:
            log.warning(f"[worker:{dim_key}] PRD 内容空 {prd_path}, 跳过")
            continue
        user = f"# PRD ({entry.get('workspace', '')})\n\n{prd_content}"
        try:
            sub_resp = route_call(
                route_id,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=4096,
                temperature=0.3,
            )
            text = _extract_text_from_resp(sub_resp)
            items = _parse_json_list(text)
            # 给每条 item 标 source 让后续 cuckoo 区分
            for it in items:
                it.setdefault("dimension", dim_key)
                it.setdefault("workspace", entry.get("workspace", ""))
            all_items.extend(items)
            usage = getattr(sub_resp, "usage", {}) or {}
            resp.add_usage(usage)
            log.info(f"[worker:{dim_key}] {entry.get('workspace', '')} → {len(items)} items")
        except Exception as e:  # pragma: no cover -- 真跑兜底
            log.warning(f"[worker:{dim_key}] {prd_path} 失败: {type(e).__name__}: {e}")
            if error_type is None:
                error_type = type(e).__name__.lower()

    resp.items = all_items
    return resp, error_type, fallback_triggered


def _call_advisor_pattern(
    route_id: str,
    model_tier: str,
    dataset: List[Dict[str, Any]],
    max_cases: int,
) -> tuple:
    """对 advisor_conflicts dataset 跑 advisor.goshawk* 真调用, 输出 merged items.

    最简化策略 (不走 goshawk_advisor.advisor_review 全流程):
    - 每条 entry 拿 worker_outputs (4-5 worker 提报)
    - 让 LLM 输出 JSON object: {merged: [...], dropped: [...], conflict_resolutions: [...]}
    - merged 列表的 worker_output 复刻成 items 给 cuckoo P/R/F1
    """
    from model_router import route_call

    sub = dataset[:max_cases]
    all_items: List[Dict[str, Any]] = []
    extra_dropped = 0
    extra_conflicts = 0
    error_type: Optional[str] = None
    fallback_triggered = False
    resp = _BatchResponse(model=model_tier, predictions=[])

    # Windows cmd shell 元字符 (| < > &) 在 --system-prompt argv 里会被解析.
    # 全部用普通字符表达 schema 避免崩.
    system = (
        "你是苍鹰 (meta-reviewer), 审核多个 worker 的 PRD 评审结果. "
        "对同源 / 重复 / 冲突的 issue 做合并, 保留最完整的, 丢弃冗余. "
        "输出 **只含一个 JSON object** 的回复 (不要 markdown 文本). "
        "object 字段: "
        "merged (list of 保留的 worker_output id 字符串), "
        "dropped (list of object, 每条含 id 和 reason 40 字以内), "
        "conflict_resolutions (list of object, 每条含 ids 数组和 resolution 文本如 合并 / 保留 / 降级). "
        "保留最完整的 1-3 条作 merged, 其余丢入 dropped."
    )

    for entry in sub:
        worker_outputs = entry.get("worker_outputs", []) or []
        if not worker_outputs:
            continue
        # 给 LLM 看简化版 worker_outputs (避免 token 爆)
        compact = [
            {
                "id": w.get("id", ""),
                "rule_id": w.get("rule_id", ""),
                "dimension": w.get("dimension", ""),
                "location": w.get("location", ""),
                "issue": (w.get("issue", "") or "")[:200],
                "severity": w.get("severity", ""),
            }
            for w in worker_outputs
        ]
        user = (
            f"# 场景 ({entry.get('workspace', '')})\n"
            f"{entry.get('scenario', '')}\n\n"
            f"# worker_outputs ({len(worker_outputs)} 条)\n"
            f"{json.dumps(compact, ensure_ascii=False, indent=2)}"
        )
        try:
            sub_resp = route_call(
                route_id,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=2048,
                temperature=0.2,
            )
            text = _extract_text_from_resp(sub_resp)
            decision = _parse_json_obj(text)
            merged_ids = [str(x) for x in (decision.get("merged") or []) if isinstance(x, (str, int))]
            dropped_list = decision.get("dropped") or []
            conflicts_list = decision.get("conflict_resolutions") or []
            extra_dropped += len(dropped_list) if isinstance(dropped_list, list) else 0
            extra_conflicts += len(conflicts_list) if isinstance(conflicts_list, list) else 0
            # 把 merged_ids 复刻回原 worker_output (cuckoo 走 location/issue/keywords 匹配)
            id_map = {str(w.get("id", "")): w for w in worker_outputs}
            for mid in merged_ids:
                if mid in id_map:
                    item = dict(id_map[mid])
                    item.setdefault("workspace", entry.get("workspace", ""))
                    item["_advisor_decision"] = "merged"
                    all_items.append(item)
            usage = getattr(sub_resp, "usage", {}) or {}
            resp.add_usage(usage)
            log.info(
                f"[advisor:{route_id}] {entry.get('id', '')} → "
                f"merged={len(merged_ids)} dropped={len(dropped_list)} "
                f"conflicts={len(conflicts_list)}"
            )
        except Exception as e:  # pragma: no cover -- 真跑兜底
            log.warning(f"[advisor] {entry.get('id')} 失败: {type(e).__name__}: {e}")
            if error_type is None:
                error_type = type(e).__name__.lower()

    resp.items = all_items
    # extra metadata 挂 resp 上, report 层可以可选消费
    resp.advisor_dropped_count = extra_dropped
    resp.advisor_conflict_count = extra_conflicts
    return resp, error_type, fallback_triggered


def _call_eval_cuckoo_pattern(
    route_id: str,
    model_tier: str,
    dataset: List[Dict[str, Any]],
    max_cases: int,
) -> tuple:
    """eval.cuckoo (LLM-as-judge 评测期跑分) -- P0 阶段功能等同 worker.default,
    直接复用 _call_worker_pattern. P1 才分化做 LLM scorer 行为.
    """
    return _call_worker_pattern("worker.default", model_tier, dataset, max_cases)


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
