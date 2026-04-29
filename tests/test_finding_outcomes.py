"""finding_outcomes_store + feedback API + dashboard 单元测试."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import pytest

# 确保项目根 import 路径
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from review.finding_outcomes_store import (
    get_all_rules_metrics,
    get_finding_latest_outcome,
    get_high_accept_rules,
    get_low_accept_rules,
    get_pm_accept_history,
    get_pm_accept_summary,
    get_recent_outcomes,
    get_rule_accept_rate,
    init_store,
    record_outcome,
    trend_buckets,
)


@pytest.fixture
def temp_db(tmp_path):
    """每个测试一个干净 sqlite db."""
    db_path = str(tmp_path / "test_outcomes.db")
    init_store(db_path)
    yield db_path


# ============================================================
# 基础 record / read
# ============================================================


def test_init_store_idempotent(tmp_path):
    """init_store 重复调用不报错."""
    db = str(tmp_path / "x.db")
    init_store(db)
    init_store(db)
    assert os.path.exists(db)


def test_record_and_read_basic(temp_db):
    """写一条, 立刻能读出来."""
    record_outcome(
        finding_id="R-001",
        outcome="accept",
        rule_id="R-001",
        pm_name="alice",
        db_path=temp_db,
    )
    m = get_rule_accept_rate("R-001", days=30, db_path=temp_db)
    assert m["accept"] == 1
    assert m["reject"] == 0
    assert m["total"] == 1
    assert m["accept_rate"] == 1.0


def test_record_invalid_outcome_raises(temp_db):
    """outcome 非法值必须抛."""
    with pytest.raises(ValueError):
        record_outcome(finding_id="R-001", outcome="invalid", db_path=temp_db)


def test_record_missing_finding_id_raises(temp_db):
    with pytest.raises(ValueError):
        record_outcome(finding_id="", outcome="accept", db_path=temp_db)


def test_record_outcome_with_all_fields(temp_db):
    """所有可选字段写入后能读出."""
    record_outcome(
        finding_id="RC-005",
        outcome="reject",
        rule_id="RC-005",
        pm_name="pm_潘驰",
        reason="分页字段已统一",
        workspace="workspace-sample",
        prd_name="某 PRD",
        severity="must",
        db_path=temp_db,
    )
    latest = get_finding_latest_outcome("RC-005", db_path=temp_db)
    assert latest is not None
    assert latest["outcome"] == "reject"
    assert latest["pm_name"] == "pm_潘驰"
    assert latest["reason"] == "分页字段已统一"
    assert latest["severity"] == "must"


# ============================================================
# accept_rate 算法
# ============================================================


def test_accept_rate_with_edit_as_half(temp_db):
    """edit 当 0.5 个 accept."""
    # 2 accept + 1 edit + 1 reject = 4 total
    # accept_rate = (2 + 1 * 0.5) / 4 = 0.625
    for _ in range(2):
        record_outcome("R-A", "accept", rule_id="R-A", db_path=temp_db)
    record_outcome("R-A", "edit", rule_id="R-A", reason="改写", db_path=temp_db)
    record_outcome("R-A", "reject", rule_id="R-A", db_path=temp_db)
    m = get_rule_accept_rate("R-A", days=30, db_path=temp_db)
    assert m["total"] == 4
    assert m["accept_rate"] == 0.625


def test_zero_count_accept_rate(temp_db):
    """没数据时 accept_rate=0, 不抛除零."""
    m = get_rule_accept_rate("不存在", days=30, db_path=temp_db)
    assert m["total"] == 0
    assert m["accept_rate"] == 0.0


# ============================================================
# 聚合: all_rules / pm_summary
# ============================================================


def test_get_all_rules_metrics(temp_db):
    """多条规则聚合."""
    record_outcome("R-1", "accept", rule_id="R-1", db_path=temp_db)
    record_outcome("R-1", "accept", rule_id="R-1", db_path=temp_db)
    record_outcome("R-2", "reject", rule_id="R-2", db_path=temp_db)
    metrics = get_all_rules_metrics(days=30, db_path=temp_db)
    assert "R-1" in metrics
    assert metrics["R-1"]["accept"] == 2
    assert metrics["R-2"]["reject"] == 1
    assert metrics["R-2"]["accept_rate"] == 0.0


def test_get_pm_accept_summary(temp_db):
    record_outcome("R-1", "accept", rule_id="R-1", pm_name="alice", db_path=temp_db)
    record_outcome("R-2", "reject", rule_id="R-2", pm_name="alice", db_path=temp_db)
    record_outcome("R-3", "accept", rule_id="R-3", pm_name="bob", db_path=temp_db)
    summary = get_pm_accept_summary(days=30, db_path=temp_db)
    assert summary["alice"]["total"] == 2
    assert summary["alice"]["accept_rate"] == 0.5
    assert summary["bob"]["total"] == 1
    assert summary["bob"]["accept_rate"] == 1.0


def test_get_pm_accept_history(temp_db):
    record_outcome("R-1", "accept", rule_id="R-1", pm_name="alice", db_path=temp_db)
    record_outcome("R-2", "reject", rule_id="R-2", pm_name="alice", db_path=temp_db)
    history = get_pm_accept_history("alice", days=30, db_path=temp_db)
    assert len(history) == 2


# ============================================================
# low / high accept 识别
# ============================================================


def test_low_accept_rules_detected(temp_db):
    """6 条全是 reject → 进 low_accept."""
    for _ in range(6):
        record_outcome("R-bad", "reject", rule_id="R-bad", db_path=temp_db)
    low = get_low_accept_rules(threshold=0.3, min_count=5, days=30, db_path=temp_db)
    rids = [m["rule_id"] for m in low]
    assert "R-bad" in rids


def test_low_accept_skipped_when_count_low(temp_db):
    """3 条 reject, min_count=5 → 不进 low_accept (样本不足)."""
    for _ in range(3):
        record_outcome("R-bad", "reject", rule_id="R-bad", db_path=temp_db)
    low = get_low_accept_rules(threshold=0.3, min_count=5, days=30, db_path=temp_db)
    rids = [m["rule_id"] for m in low]
    assert "R-bad" not in rids


def test_high_accept_rules_detected(temp_db):
    for _ in range(6):
        record_outcome("R-good", "accept", rule_id="R-good", db_path=temp_db)
    high = get_high_accept_rules(threshold=0.95, min_count=5, days=30, db_path=temp_db)
    rids = [m["rule_id"] for m in high]
    assert "R-good" in rids


# ============================================================
# 时间窗口
# ============================================================


def test_window_filter_excludes_old(temp_db, monkeypatch):
    """超过窗口期的 outcome 不计入聚合."""
    # 写两条, 一条改成 60 天前
    record_outcome("R-old", "accept", rule_id="R-old", db_path=temp_db)
    record_outcome("R-old", "accept", rule_id="R-old", db_path=temp_db)
    # 直接 sqlite update timestamp
    import sqlite3
    conn = sqlite3.connect(temp_db)
    old_ts = (datetime.now() - timedelta(days=60)).isoformat(timespec="seconds")
    conn.execute(
        "UPDATE finding_outcomes SET timestamp = ? WHERE id = (SELECT MIN(id) FROM finding_outcomes)",
        [old_ts],
    )
    conn.commit()
    conn.close()
    # 30 天窗口只能看到 1 条
    m = get_rule_accept_rate("R-old", days=30, db_path=temp_db)
    assert m["total"] == 1
    # 90 天能看到 2 条
    m2 = get_rule_accept_rate("R-old", days=90, db_path=temp_db)
    assert m2["total"] == 2


# ============================================================
# trend buckets
# ============================================================


def test_trend_buckets_returns_correct_count(temp_db):
    """30 天 / 7 天桶 → 5 个桶 (含当前不完整周)."""
    buckets = trend_buckets(days=30, bucket_days=7, db_path=temp_db)
    assert 4 <= len(buckets) <= 5  # 边界宽容
    # 字段
    for b in buckets:
        assert "bucket_start" in b
        assert "accept" in b
        assert "accept_rate" in b


# ============================================================
# 并发安全
# ============================================================


def test_concurrent_writes_no_loss(temp_db):
    """50 条并发写, 全部能读出来."""
    import threading
    n = 50
    threads = []
    def _w(i):
        record_outcome(f"R-{i:03d}", "accept", rule_id=f"R-{i:03d}", db_path=temp_db)
    for i in range(n):
        t = threading.Thread(target=_w, args=(i,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    recent = get_recent_outcomes(limit=n + 10, db_path=temp_db)
    assert len(recent) == n


# ============================================================
# 飞书 bot feedback parser (启发式)
# ============================================================


def test_feishu_parse_reject():
    from feishu_bot import _try_parse_feedback
    fb = _try_parse_feedback("@啄木鸟 R-001 是误报, 分页字段已有约定")
    assert fb is not None
    assert fb["finding_id"] == "R-001"
    assert fb["outcome"] == "reject"
    assert "分页" in (fb["reason"] or "")


def test_feishu_parse_accept():
    from feishu_bot import _try_parse_feedback
    fb = _try_parse_feedback("@啄木鸟 RC-005 接受")
    assert fb is not None
    assert fb["outcome"] == "accept"


def test_feishu_parse_edit():
    from feishu_bot import _try_parse_feedback
    fb = _try_parse_feedback("@啄木鸟 R-003 改写: 应该直接说排序需要补充章节")
    assert fb is not None
    assert fb["outcome"] == "edit"


def test_feishu_parse_no_finding_id():
    """没 finding_id 不当反馈."""
    from feishu_bot import _try_parse_feedback
    assert _try_parse_feedback("@啄木鸟 帮我评审") is None


def test_feishu_parse_no_action_keyword():
    """有 finding_id 但没动作词不当反馈."""
    from feishu_bot import _try_parse_feedback
    assert _try_parse_feedback("R-001 是什么") is None


# ============================================================
# Dashboard 渲染
# ============================================================


def test_dashboard_renders_with_empty_db(temp_db):
    """空 db 也能渲染 (不抛)."""
    from scripts.quality_metrics_dashboard import collect_dashboard_data, render_html
    data = collect_dashboard_data(days=30, db_path=temp_db)
    html = render_html(data)
    assert "<html" in html
    assert "啄木鸟规则质量 Dashboard" in html


def test_dashboard_renders_with_data(temp_db):
    record_outcome("R-1", "accept", rule_id="R-1", pm_name="alice", db_path=temp_db)
    record_outcome("R-1", "reject", rule_id="R-1", pm_name="alice", db_path=temp_db)
    from scripts.quality_metrics_dashboard import collect_dashboard_data, render_html
    data = collect_dashboard_data(days=30, db_path=temp_db)
    html = render_html(data)
    assert "R-1" in html
    assert "alice" in html


def test_dashboard_csv_export(temp_db, tmp_path):
    record_outcome("R-1", "accept", rule_id="R-1", db_path=temp_db)
    record_outcome("R-1", "reject", rule_id="R-1", db_path=temp_db)
    from scripts.quality_metrics_dashboard import collect_dashboard_data, export_csv
    data = collect_dashboard_data(days=30, db_path=temp_db)
    csv_path = str(tmp_path / "out.csv")
    export_csv(data, csv_path)
    assert os.path.exists(csv_path)
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        content = f.read()
    assert "R-1" in content
    assert "accept_rate" in content
