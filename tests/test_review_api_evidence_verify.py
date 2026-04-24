"""T0 pre-sprint blocker — API flow 接入 verify_evidence 测试 (2026-04-24).

这个文件只测 `verify_evidence` 这一段代码在 API 路径里的"失败不阻塞 + 正常分支过滤 RETRACTED"行为.
整个 `/api/review` pipeline 的 e2e 涉及 Claude CLI / worker / goshawk,本测试不做 e2e,只做
unit-level 验证 T0 修复的三个承诺:

  1. verify_evidence 抛异常时, API flow 不中断, items 保持 merge 之后的原样
  2. verify_evidence 返回的 items 里, status == "RETRACTED" 的被过滤掉
  3. summarize_verification 的 5 个 count 字段正确落到 EventStore 里
"""
from __future__ import annotations

import pytest


# ============================================================
# 模拟 API flow 里 verify_evidence 那段 (与 api/routes/review.py:371~ 对齐)
# ============================================================

def _api_evidence_verify_block(items, ws_abs_path, evt_appender, emitter_emitter, logger):
    """提取 api/routes/review.py 里的 T0 逻辑块做独立测试.

    参数对齐原代码:
      items:           merge 后 (从 parallel_review 拿到的 merged_items)
      ws_abs_path:     工作区绝对路径
      evt_appender:    callable(event_type:str, data:dict) -> None
      emitter_emitter: callable(event_type:str, data:dict) -> None
      logger:          有 .warning(msg) 方法的对象

    返回过滤 RETRACTED 后的 items.
    """
    try:
        from review.evidence_verify import verify_evidence, summarize_verification
        verified = verify_evidence(items, ws_abs_path)
        items = [i for i in verified if i.get("status") != "RETRACTED"]
        v_sum = summarize_verification(verified)
        evt_appender("evidence_verify_done", {
            "total": v_sum.get("total", 0),
            "verified": v_sum.get("verified", 0),
            "caveat": v_sum.get("caveat", 0),
            "retracted": v_sum.get("retracted", 0),
            "reliability": v_sum.get("reliability", 0.0),
        })
        emitter_emitter("evidence_verify_done", {
            "retracted": v_sum.get("retracted", 0),
            "caveat": v_sum.get("caveat", 0),
        })
    except Exception as _ev_err:
        logger.warning(f"[evidence_verify] API flow 失败回退到跳过模式: {_ev_err}")
        evt_appender("evidence_verify_skipped", {"reason": str(_ev_err)[:200]})
    return items


# ============================================================
# Fixtures: 假的 evt / emitter / logger + 可跑的 workspace
# ============================================================

class _Recorder:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def __call__(self, event_type, data):
        self.events.append((event_type, data))


class _LogRec:
    def __init__(self):
        self.warnings: list[str] = []

    def warning(self, msg):
        self.warnings.append(msg)


@pytest.fixture
def tmp_workspace(tmp_path):
    """构造一个最小 workspace 目录, 有 wiki/ + review-rules/ 子目录."""
    ws = tmp_path / "workspace-test"
    ws.mkdir()
    (ws / "wiki").mkdir()
    (ws / "review-rules").mkdir()
    # 放一条 rule 让 B 类依据能查到
    (ws / "review-rules" / "review-checklist.yaml").write_text(
        "rules:\n  - id: RC-001\n    name: test\n",
        encoding="utf-8",
    )
    return ws


# ============================================================
# 测试: 正常路径 — verify_evidence 返回 items, RETRACTED 被过滤
# ============================================================

class TestApiEvidenceVerifyNormal:
    def test_retracted_filtered_caveat_kept(self, tmp_workspace):
        """RETRACTED 过滤, verified / verified_with_caveat 保留. 事件字段齐."""
        items = [
            # A 类 — wiki 稀疏模式下应该走 caveat (不 retract)
            {"id": "R-001", "evidence_type": "A", "evidence_content": "[[不存在页]]",
             "issue": "问题A", "confidence_score": 0.8},
            # B 类 — rule_id 存在, 走 verified
            {"id": "R-002", "evidence_type": "B", "evidence_content": "RC-001",
             "issue": "问题B", "confidence_score": 0.7},
            # B 类 — rule_id 不存在, retract
            {"id": "R-003", "evidence_type": "B", "evidence_content": "RC-999",
             "issue": "问题C", "confidence_score": 0.7},
        ]

        evt = _Recorder()
        emitter = _Recorder()
        logger = _LogRec()

        out = _api_evidence_verify_block(items, str(tmp_workspace), evt, emitter, logger)

        ids = [i["id"] for i in out]
        assert "R-003" not in ids, "B 类 rule_id 不存在的应被过滤"
        assert "R-001" in ids, "A 类稀疏模式 caveat 应保留"
        assert "R-002" in ids, "B 类 rule_id 存在应保留"

        # evt 记了 evidence_verify_done 事件
        assert len(evt.events) == 1
        assert evt.events[0][0] == "evidence_verify_done"
        payload = evt.events[0][1]
        for k in ("total", "verified", "caveat", "retracted", "reliability"):
            assert k in payload, f"event payload 缺 {k}"
        assert payload["retracted"] == 1, "R-003 应计入 retracted"
        assert payload["total"] == 3

        # emitter 也发了
        assert len(emitter.events) == 1
        assert emitter.events[0][0] == "evidence_verify_done"
        assert emitter.events[0][1]["retracted"] == 1

        # 没 warning
        assert logger.warnings == []

    def test_empty_items_does_not_break(self, tmp_workspace):
        """空 items 不 crash, evt 照样记."""
        evt = _Recorder()
        emitter = _Recorder()
        logger = _LogRec()

        out = _api_evidence_verify_block([], str(tmp_workspace), evt, emitter, logger)
        assert out == []
        assert len(evt.events) == 1
        assert evt.events[0][1]["total"] == 0
        assert logger.warnings == []


# ============================================================
# 测试: 失败不阻塞 — verify_evidence 抛异常, items 原样返回, log warning
# ============================================================

class TestApiEvidenceVerifyFailSafe:
    def test_verify_evidence_exception_does_not_block(self, monkeypatch, tmp_workspace):
        """mock verify_evidence 抛异常, 断言 items 保持原样 + evt 记 skipped + log 有 warning."""
        def _raise(*args, **kwargs):
            raise RuntimeError("boom — 模拟 evidence_verify 内部崩了")

        monkeypatch.setattr("review.evidence_verify.verify_evidence", _raise)

        items = [
            {"id": "R-001", "evidence_type": "A", "evidence_content": "..."},
            {"id": "R-002", "evidence_type": "B", "evidence_content": "RC-001"},
        ]
        evt = _Recorder()
        emitter = _Recorder()
        logger = _LogRec()

        out = _api_evidence_verify_block(items, str(tmp_workspace), evt, emitter, logger)

        # items 原样返回 — 没因异常丢条
        assert len(out) == 2
        assert {i["id"] for i in out} == {"R-001", "R-002"}

        # evt 记的是 skipped 而不是 done
        assert len(evt.events) == 1
        assert evt.events[0][0] == "evidence_verify_skipped"
        assert "boom" in evt.events[0][1]["reason"]

        # emitter 没发 (只在成功分支发)
        assert emitter.events == []

        # log 有 warning
        assert len(logger.warnings) == 1
        assert "失败回退" in logger.warnings[0]

    def test_workspace_not_exists_does_not_block(self, tmp_path):
        """不存在的 workspace 路径也不阻塞 — verify_evidence 内部有兜底, 但外层 try 也兜."""
        items = [{"id": "R-001", "evidence_type": "A", "evidence_content": "..."}]
        evt = _Recorder()
        emitter = _Recorder()
        logger = _LogRec()

        fake_ws = str(tmp_path / "does-not-exist")
        out = _api_evidence_verify_block(items, fake_ws, evt, emitter, logger)

        # verify_evidence 内部对不存在目录兼容 (sparse 模式), 不抛异常 → 走成功分支
        assert len(out) >= 1
        assert len(evt.events) == 1
        # 期望 evidence_verify_done, 不是 skipped (因为 verify_evidence 自己兜住了)
        assert evt.events[0][0] == "evidence_verify_done"
