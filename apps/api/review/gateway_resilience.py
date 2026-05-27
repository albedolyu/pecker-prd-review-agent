"""Gateway and worker failure classification for review orchestration."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional


_TRANSIENT_TYPES = {
    "timeout",
    "gateway_timeout",
    "gateway_502",
    "rate_limit",
    "api_unavailable",
    "network",
    "server_error",
}


def classify_worker_error(error: Any) -> str:
    """Classify worker/provider failures into stable operational buckets."""
    text = f"{type(error).__name__}: {error}".lower() if isinstance(error, BaseException) else str(error or "").lower()
    if "524" in text or "a timeout occurred" in text:
        return "gateway_timeout"
    if "504" in text or "gateway timeout" in text:
        return "gateway_timeout"
    if "502" in text or "bad gateway" in text:
        return "gateway_502"
    if "429" in text or "rate limit" in text or "too many request" in text:
        return "rate_limit"
    if "503" in text or "no available account" in text or "upstream_error" in text:
        return "api_unavailable"
    if "timed out" in text or "timeout" in text or "超时" in text:
        return "timeout"
    if "connection" in text or "connect" in text or "reset" in text:
        return "network"
    if "500" in text or "520" in text or "522" in text or "server error" in text:
        return "server_error"
    return "unknown"


def is_transient_error_type(error_type: str) -> bool:
    return error_type in _TRANSIENT_TYPES


def build_resilience_summary(
    workers: Iterable[Dict[str, Any]],
    *,
    current_batch_size: Optional[int] = None,
    total_workers: Optional[int] = None,
) -> Dict[str, Any]:
    """Summarize worker failures and propose the next runtime adjustment."""
    worker_rows = list(workers)
    failed = [worker for worker in worker_rows if worker.get("error")]
    error_types = Counter(
        worker.get("error_type") or classify_worker_error(worker.get("error"))
        for worker in failed
    )
    transient_failures = sum(
        count for error_type, count in error_types.items()
        if is_transient_error_type(str(error_type))
    )
    context_packet_chars = [
        int((worker.get("telemetry") or {}).get("prd_context_packet_chars") or 0)
        for worker in worker_rows
    ]
    context_packet_workers = sum(1 for value in context_packet_chars if value > 0)
    recovered_workers = sum(
        1
        for worker in worker_rows
        if worker.get("status") == "recovered" or bool(worker.get("recovery"))
    )
    total = int(total_workers or len(worker_rows) or 0)
    batch = int(current_batch_size or total or 1)

    suggested_actions: List[str] = []
    recommended_batch_size = batch
    if any(error_type in error_types for error_type in ("gateway_timeout", "gateway_502", "rate_limit")):
        recommended_batch_size = max(1, batch - 1)
        suggested_actions.append("降低同时评审方向数")
    if "gateway_timeout" in error_types or "timeout" in error_types:
        suggested_actions.append("启用超时恢复或压缩知识库上下文")
        suggested_actions.append("未完整返回的方向可改用稳定线路或恢复模式")
    if "api_unavailable" in error_types:
        suggested_actions.append("检查中转站额度和可用账号")
    if not suggested_actions and failed:
        suggested_actions.append("查看失败原文后重新评审")

    return {
        "failed_workers": len(failed),
        "total_workers": total,
        "transient_failures": transient_failures,
        "error_types": dict(error_types),
        "current_batch_size": batch,
        "recommended_batch_size": recommended_batch_size,
        "context_packet_workers": context_packet_workers,
        "max_context_packet_chars": max(context_packet_chars, default=0),
        "recovered_workers": recovered_workers,
        "suggested_actions": suggested_actions,
    }
