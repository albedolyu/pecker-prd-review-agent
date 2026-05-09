from __future__ import annotations


def test_build_prd_context_packet_keeps_outline_and_dimension_excerpt():
    from review.prd_context import build_prd_context_packet

    prd = "\n\n".join(
        [
            "# 目标",
            "本次要支持积分抵扣和订单结算。",
            "## 字段口径",
            "refund_count 字段来自订单表,需要说明 JOIN 口径。" + "A" * 1200,
            "## 交互体验",
            "空态、异常态和文案需要说明。" + "B" * 1200,
            "## 实现边界",
            "接口依赖、权限和超时兜底需要说明。" + "C" * 1200,
        ]
    )

    packet = build_prd_context_packet(prd, dim_key="data_quality", max_chars=1000)

    assert "## PRD 结构索引" in packet
    assert "字段口径" in packet
    assert "本次要支持积分抵扣" in packet
    assert "refund_count" in packet
    assert "空态、异常态和文案" not in packet
    assert len(packet) <= 1100


def test_prd_context_packet_preserves_source_line_ranges_for_pm_confirmation():
    from review.prd_context import build_prd_context_packet

    prd = "\n".join(
        [
            "# 目标",
            "本次支持积分抵扣。",
            "## 字段口径",
            "refund_count 字段来自订单表，需要说明 JOIN 口径。" + "A" * 1200,
            "## 体验说明",
            "支付失败时要提示返还积分。",
        ]
    )

    packet = build_prd_context_packet(prd, dim_key="data_quality", max_chars=900)

    assert "字段口径（原文第 3-4 行）" in packet
    assert "目标（原文第 1-2 行）" in packet


def test_worker_messages_use_compact_prd_packet_in_recovery_mode():
    from review.prompting import _build_worker_messages

    prd = "# 字段口径\nrefund_count 字段来自订单表。" + ("A" * 5000)
    packet = "## PRD 结构索引\n- 字段口径\n\n## 本维度相关摘录\nrefund_count 字段来自订单表。"

    messages = _build_worker_messages(
        prd,
        {},
        dim_key="data_quality",
        wiki_keywords={"data_quality": ["字段", "refund_count"]},
        recovery_mode=True,
        prd_context_packet=packet,
    )

    content = messages[0]["content"]
    assert "## 待评审 PRD（压缩视图）" in content
    assert packet in content
    assert "A" * 1000 not in content


def test_worker_messages_ask_for_original_line_ranges_when_using_packet():
    from review.prompting import _build_worker_messages

    packet = "## PRD 结构索引\n- 字段口径（原文第 3-4 行）\n\n## 本维度相关摘录\n### 字段口径（原文第 3-4 行）\nrefund_count 字段来自订单表"

    messages = _build_worker_messages(
        "full prd hidden",
        {},
        dim_key="data_quality",
        wiki_keywords={"data_quality": ["字段", "refund_count"]},
        recovery_mode=False,
        prd_context_packet=packet,
    )

    content = messages[0]["content"]
    assert "位置字段优先写成“原文第 X-Y 行 + 章节名”" in content
    assert "原文第 3-4 行" in content


def test_worker_messages_ask_for_searchable_locations():
    from review.prompting import _build_worker_messages

    messages = _build_worker_messages(
        "# 目标\n本次支持积分抵扣。\n## 字段口径\nrefund_count 字段来自订单表。",
        {},
        dim_key="structure",
        wiki_keywords={"structure": ["目标", "范围"]},
    )

    content = messages[0]["content"]
    assert "location / 位置请写成可在 PRD 中搜索到的短句、章节名或原文行号" in content
    assert "避免只写“全文/整体/上述”" in content


def test_should_use_prd_packet_auto_only_for_large_prd_or_recovery(monkeypatch):
    from review.prd_context import should_use_prd_context_packet

    monkeypatch.delenv("PECKER_PRD_CONTEXT_MODE", raising=False)
    monkeypatch.delenv("PECKER_PRD_CONTEXT_AUTO_CHARS", raising=False)
    assert should_use_prd_context_packet("short prd", {}, recovery_mode=False) is False
    assert should_use_prd_context_packet("x" * 40_000, {}, recovery_mode=False) is True
    assert should_use_prd_context_packet("short prd", {}, recovery_mode=True) is True


def test_prd_packet_default_threshold_matches_team_beta_target(monkeypatch):
    from review.prd_context import (
        prd_context_auto_threshold_chars,
        should_use_prd_context_packet,
    )

    monkeypatch.delenv("PECKER_PRD_CONTEXT_MODE", raising=False)
    monkeypatch.delenv("PECKER_PRD_CONTEXT_AUTO_CHARS", raising=False)

    assert prd_context_auto_threshold_chars() == 12_000
    assert should_use_prd_context_packet("x" * 11_999, {}, recovery_mode=False) is False
    assert should_use_prd_context_packet("x" * 12_000, {}, recovery_mode=False) is True


def test_prd_section_split_is_cached_across_worker_dimensions():
    from review.prd_context import _split_sections_cached, build_prd_context_packet

    prd = "\n".join(
        [
            "# Goal",
            "A" * 20_000,
            "## Data",
            "field mapping " + "B" * 20_000,
            "## Risk",
            "timeout fallback " + "C" * 20_000,
        ]
    )

    _split_sections_cached.cache_clear()
    build_prd_context_packet(prd, dim_key="data_quality", max_chars=1200)
    first = _split_sections_cached.cache_info()
    build_prd_context_packet(prd, dim_key="ai_coding", max_chars=1200)
    second = _split_sections_cached.cache_info()

    assert first.misses == 1
    assert second.misses == 1
    assert second.hits >= first.hits + 1


def test_should_use_prd_packet_auto_threshold_is_deploy_tunable(monkeypatch):
    from review.prd_context import (
        prd_context_auto_threshold_chars,
        should_use_prd_context_packet,
    )

    monkeypatch.delenv("PECKER_PRD_CONTEXT_MODE", raising=False)
    monkeypatch.setenv("PECKER_PRD_CONTEXT_AUTO_CHARS", "12000")

    assert prd_context_auto_threshold_chars() == 12000
    assert should_use_prd_context_packet("x" * 11_999, {}, recovery_mode=False) is False
    assert should_use_prd_context_packet("x" * 12_000, {}, recovery_mode=False) is True


def test_run_worker_async_passes_packet_for_large_prd_auto(monkeypatch):
    import asyncio

    from review import worker as worker_mod

    calls = []

    def fake_worker_core(*_args, **kwargs):
        calls.append(kwargs)
        return {
            "dimension": "data_quality",
            "items": [],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.delenv("PECKER_PRD_CONTEXT_MODE", raising=False)
    monkeypatch.setattr(worker_mod, "_worker_core", fake_worker_core)

    async def run():
        return await worker_mod._run_worker_async(
            None,
            "data_quality",
            "# 字段口径\nrefund_count 字段来自订单表。" + ("A" * 40_000),
            {},
            {},
        )

    asyncio.run(run())

    assert calls[0]["recovery_mode"] is False
    assert calls[0]["prd_context_packet"]
    assert len(calls[0]["prd_context_packet"]) < 20_000
