"""Audit coverage for legacy context-management paths."""

from types import SimpleNamespace
from unittest.mock import MagicMock


def test_microcompact_audit_records_usage_and_saved_tokens():
    from context_manager import (
        get_context_audit_snapshot,
        microcompact,
        reset_context_audit,
    )

    reset_context_audit()
    long_content = "工具执行结果：" + "A" * 3000
    messages = [
        {"role": "user", "content": long_content},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "next"},
        {"role": "assistant", "content": "ok2"},
    ]

    microcompact(messages)

    snapshot = get_context_audit_snapshot()
    path = snapshot["paths"]["microcompact"]
    assert path["calls"] == 1
    assert path["mutations"] == 1
    assert path["tokens_saved"] > 0
    assert snapshot["total_tokens_saved"] == path["tokens_saved"]


def test_check_convergence_audit_records_nudges():
    from context_manager import (
        check_convergence,
        get_context_audit_snapshot,
        reset_context_audit,
    )

    reset_context_audit()
    messages = [
        {"role": "user", "content": "start"},
        {"role": "assistant", "content": "a"},
        {"role": "user", "content": "next"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "next"},
        {"role": "assistant", "content": "c"},
    ]

    assert check_convergence(messages, threshold=3) is not None

    snapshot = get_context_audit_snapshot()
    path = snapshot["paths"]["check_convergence"]
    assert path["calls"] == 1
    assert path["nudges"] == 1


def test_autocompact_audit_records_success_savings():
    from context_manager import (
        AutocompactManager,
        KEEP_RECENT_MESSAGES,
        get_context_audit_snapshot,
        reset_context_audit,
    )

    reset_context_audit()
    mgr = AutocompactManager()
    messages = [
        {"role": "user", "content": ("old context " * 200)}
        for _ in range(KEEP_RECENT_MESSAGES + 3)
    ]
    client = MagicMock()
    client.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="summary")],
    )

    compacted = mgr.compact(client, messages, {"haiku": "h", "sonnet": "s"})

    assert compacted is not messages
    snapshot = get_context_audit_snapshot()
    path = snapshot["paths"]["autocompact"]
    assert path["calls"] == 1
    assert path["mutations"] == 1
    assert path["tokens_saved"] > 0
    assert path["failures"] == 0
