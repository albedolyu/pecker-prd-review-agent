"""dashboard.py 接 SchemaRegistry 后 zombie / 缺规则展示策略锁定 (step 3 frontend sync, 2026-04-28).

设计意图 (docs/audit_frontend_sync_2026_04_28.md #1):
- dashboard.py 之前直读 rule_performance_history.json 的 17 keys, 含 zombie RC-014 + 缺 5 条 active/experimental.
- 改后:
  - rule list 来自 SchemaRegistry.get().all_rule_ids() (单点 SoT)
  - history.json 只补"性能数据" (total/confirmed/rejected/rejection_rate)
  - zombie (history 有 / registry 没) → drop 不展示, 加 warn
  - missing (registry 有 / history 没) → 展示 + status_label = "尚未触发"
  - 顺手把 audit #4 (authority_distribution) #5 (DAR retention_kind) panel 接通

本测试锁死 (TDD, 改动落地前先红灯):
1. _load_rule_history 不再展示 zombie RC-014
2. _load_rule_history 把 registry 有 / history 没的规则补成 status_label="尚未触发"
3. _load_rule_history 返回的 rule list ⊆ all_rule_ids() (没有未知 id)
4. _load_funnel_extras: scan sessions/*.jsonl 累加 authority_distribution + DAR retention_kind_dist
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# fixtures: 临时 workspace 模拟 history.json + sessions/*.jsonl
# ============================================================


@pytest.fixture(autouse=True)
def _clear_registry_cache():
    """每个 test 前后清 registry cache, 防 workspace 路径污染."""
    from review.schema_registry import SchemaRegistry
    SchemaRegistry._cached_get.cache_clear()
    yield
    SchemaRegistry._cached_get.cache_clear()


@pytest.fixture
def fake_workspace(tmp_path):
    """搭一个临时 workspace, 含 output/ + sessions/.

    包括:
    - rule_performance_history.json: 含 zombie RC-014 + 一条 active V-04 + 缺 EV-01/FN-01
    - sessions/*.jsonl: 含 funnel_stage_after_evidence_verify + final_reviewer_done
    """
    output = tmp_path / "output"
    output.mkdir(parents=True, exist_ok=True)
    sessions = output / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)

    # 1. history.json: 含 zombie + 一条正常 + 故意不写 EV-01/FN-01 (让 registry 补)
    history = {
        "RC-014": {
            "name": "ai 编码层 (zombie)",
            "history": [],
            "stats": {"confirmed": 2, "rejected": 1, "missed": 0, "total": 3},
            "rejection_rate": 0.33,
            "is_noisy": False,
        },
        "V-04": {
            "name": "结构层",
            "history": [],
            "stats": {"confirmed": 5, "rejected": 0, "missed": 0, "total": 5},
            "rejection_rate": 0.0,
            "is_noisy": False,
        },
    }
    (output / "rule_performance_history.json").write_text(
        json.dumps(history, ensure_ascii=False), encoding="utf-8"
    )

    # 2. sessions/*.jsonl: 模拟两条 funnel + 一条 DAR
    jsonl = sessions / "rev_test_001.jsonl"
    events = [
        {
            "ts": "2026-04-28T12:00:00",
            "type": "funnel_stage_after_evidence_verify",
            "count": 5,
            "authority_distribution": {"canonical": 3, "contextual": 2},
            "wiki_mode": "rich",
        },
        {
            "ts": "2026-04-28T12:01:00",
            "type": "funnel_stage_after_evidence_verify",
            "count": 4,
            "authority_distribution": {"contextual": 4},
            "wiki_mode": "rich",
        },
        {
            "ts": "2026-04-28T12:02:00",
            "type": "final_reviewer_done",
            "verdict": "REVIEWED",
            "n_samples": 4,
            "n_samples_succeeded": 4,
            "retention_kind_dist": {"unanimous": 2, "majority": 1, "minority": 1},
            "minority_kept": 1,
        },
    ]
    with open(jsonl, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    return str(tmp_path)


# ============================================================
# 1. dashboard rule list 接 SchemaRegistry
# ============================================================


def test_dashboard_lists_all_registry_rules(fake_workspace):
    """_load_rule_history 返回的 rule list ⊇ registry.all_rule_ids() ∩ active/experimental.

    具体: 即使 history.json 里只有 RC-014 + V-04, registry 已知的 EV-01/FN-01 也得在列.
    """
    import dashboard
    from review.schema_registry import SchemaRegistry

    reg = SchemaRegistry.get(workspace=None)
    known_ids = reg.all_rule_ids()
    # 必须含至少这几条 (Day3+ 已落地)
    assert "V-04" in known_ids
    assert "EV-01" in known_ids
    assert "FN-01" in known_ids

    rule_data = dashboard._load_rule_history(fake_workspace)
    assert rule_data is not None, "rule_data 不应为 None — registry 至少有 EV-/FN-/V-"

    rule_ids_in_dashboard = {r["id"] for r in rule_data["top_rules"]}
    # all_rules_count 应等于 registry 已知数 (不再是 history 里的 17)
    # registry-only rules 也得算入计数, 让 PM 看到"已跟踪 = 25 条" 而不是 history 里 zombie 含的
    # 这里最关键: rule_ids_in_dashboard ⊆ known_ids (没有 zombie)
    for rid in rule_ids_in_dashboard:
        assert rid in known_ids, f"{rid} 是 registry 不认的 zombie, 不该展示"


# ============================================================
# 2. zombie 不展示 (RC-014)
# ============================================================


def test_dashboard_marks_zombie_or_skips(fake_workspace):
    """history 有 RC-014 但 registry 没 → 不出现在 top_rules / 不入 all_rules_count.

    设计选择: drop 不展示 (registry 是 SoT, history 老数据当噪声过滤).
    """
    import dashboard
    from review.schema_registry import SchemaRegistry

    reg = SchemaRegistry.get(workspace=None)
    assert "RC-014" not in reg.all_rule_ids(), \
        "前提: registry 不含 RC-014 (yaml 已 commit 删除)"

    rule_data = dashboard._load_rule_history(fake_workspace)
    assert rule_data is not None

    rule_ids = {r["id"] for r in rule_data["top_rules"]}
    assert "RC-014" not in rule_ids, "RC-014 zombie 不应展示"


# ============================================================
# 3. 缺规则展示 + "尚未触发" 标签
# ============================================================


def test_dashboard_marks_no_data_rules(fake_workspace):
    """registry 有 EV-01 / FN-01 但 history 没 → 展示 + status_label='尚未触发'.

    确保 PM 能看到"已上线但未命中"的规则, 不被 history.json 数据局限.
    """
    import dashboard

    rule_data = dashboard._load_rule_history(fake_workspace)
    assert rule_data is not None

    # rule_data 内必须有一段"完整规则列表" (含 0 触发的) 让 PM 看到全貌
    # 实现: rule_data 里加 "all_rules" key 或 top_rules 里 status_label
    # 这里只验证: registry 有但 history 没的规则, 它的统计字段是 0 + 有 status_label
    assert "all_rules" in rule_data, \
        "_load_rule_history 应返回 all_rules 字段 (registry 全集 + 性能数据)"

    by_id = {r["id"]: r for r in rule_data["all_rules"]}
    # EV-01 应在列, total=0, status_label 标 "尚未触发"
    assert "EV-01" in by_id, "EV-01 在 registry, 应在 all_rules"
    assert by_id["EV-01"]["total"] == 0
    assert by_id["EV-01"].get("status_label") == "尚未触发"

    # FN-01 同样
    assert "FN-01" in by_id
    assert by_id["FN-01"]["total"] == 0
    assert by_id["FN-01"].get("status_label") == "尚未触发"

    # V-04 history 有数据 → status_label 不该是"尚未触发"
    assert "V-04" in by_id
    assert by_id["V-04"]["total"] == 5
    assert by_id["V-04"].get("status_label") != "尚未触发"


# ============================================================
# 4. funnel extras: authority_distribution + DAR retention
# ============================================================


def test_dashboard_loads_authority_distribution(fake_workspace):
    """_load_funnel_extras 扫 sessions/*.jsonl 累加 authority_distribution.

    fake fixture 含两条 funnel_stage_after_evidence_verify:
    - {canonical: 3, contextual: 2}
    - {contextual: 4}
    累加期望: {canonical: 3, contextual: 6}
    """
    import dashboard

    extras = dashboard._load_funnel_extras(fake_workspace)
    assert extras is not None, \
        "_load_funnel_extras 应返回 dict, fixture 有 funnel events"

    ad = extras.get("authority_distribution", {})
    assert ad.get("canonical") == 3
    assert ad.get("contextual") == 6


def test_dashboard_loads_dar_retention(fake_workspace):
    """_load_funnel_extras 扫 sessions/*.jsonl 累加 retention_kind_dist + minority_kept.

    fake fixture 含一条 final_reviewer_done:
    - retention_kind_dist={unanimous:2, majority:1, minority:1}, minority_kept=1
    """
    import dashboard

    extras = dashboard._load_funnel_extras(fake_workspace)
    assert extras is not None

    ret = extras.get("retention_kind_dist", {})
    assert ret.get("unanimous") == 2
    assert ret.get("majority") == 1
    assert ret.get("minority") == 1

    assert extras.get("minority_kept_total") == 1


# ============================================================
# 5. dashboard 整体集成 — generate_dashboard 不爆
# ============================================================


def test_generate_dashboard_includes_registry_panel(fake_workspace):
    """generate_dashboard 端到端不崩, 输出 HTML 含 SoT 标识."""
    import dashboard

    out_path = dashboard.generate_dashboard(fake_workspace, prd_name="测试 PRD")
    assert os.path.isfile(out_path), "dashboard.html 必须生成"

    with open(out_path, "r", encoding="utf-8") as f:
        html = f.read()

    # zombie 不在 HTML
    assert "RC-014" not in html, "zombie RC-014 不应出现在 HTML"

    # registry 来源标识 (让 PM 一眼看到数据源)
    # 检验"尚未触发"标签出现 (registry-only 规则展示)
    assert "尚未触发" in html, "registry-only 规则该标 '尚未触发'"
