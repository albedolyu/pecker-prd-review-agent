from __future__ import annotations


def test_classify_worker_error_recognizes_gateway_and_timeout_failures():
    from review.gateway_resilience import classify_worker_error

    assert classify_worker_error("Cloudflare 524: a timeout occurred") == "gateway_timeout"
    assert classify_worker_error("502 Bad Gateway from upstream") == "gateway_502"
    assert classify_worker_error("HTTP 504 Gateway Timeout") == "gateway_timeout"
    assert classify_worker_error("Request timed out.") == "timeout"
    assert classify_worker_error("429 rate limit exceeded") == "rate_limit"


def test_build_resilience_summary_recommends_lower_batch_for_gateway_errors():
    from review.gateway_resilience import build_resilience_summary

    summary = build_resilience_summary(
        [
            {
                "dimension": "structure",
                "error": "Cloudflare 524: a timeout occurred",
                "telemetry": {"prd_context_packet_chars": 8192},
            },
            {
                "dimension": "risk",
                "items": [{"id": "ok"}],
                "status": "recovered",
                "telemetry": {"prd_context_packet_chars": 6000},
            },
        ],
        current_batch_size=2,
        total_workers=4,
    )

    assert summary["failed_workers"] == 1
    assert summary["transient_failures"] == 1
    assert summary["error_types"] == {"gateway_timeout": 1}
    assert summary["recommended_batch_size"] == 1
    assert summary["context_packet_workers"] == 2
    assert summary["max_context_packet_chars"] == 8192
    assert summary["recovered_workers"] == 1
    actions = "；".join(summary["suggested_actions"])
    assert "降低同时评审方向数" in actions
    assert "未完整返回的方向可改用稳定线路或恢复模式" in actions
    assert "失败方向" not in actions
    assert "worker" not in actions.lower()
