"""cuckoo_adapter._flatten_responses_to_items 三种 response 形态的回归测.

2026-04-27: C agent worker 真跑暴露 pre-existing bug — runner.all_responses
是 List[List[item]] 形态 (每 run 一个 items list 直接 append), 但 adapter
原代码只识别 List[dict] / List[response对象], 导致 items 永远 0 / P/R/F1=0.

修法在 cuckoo_adapter.py 加 isinstance(resp, list) 分支. 本测试覆盖三种
形态确保未来 runner 形态变化时能立刻发现 adapter 不兼容.
"""
from __future__ import annotations

from eval.route_eval.scorers.cuckoo_adapter import _flatten_responses_to_items


def _make_item(rule_id: str, severity: str = "must"):
    return {
        "rule_id": rule_id,
        "issue": f"issue-{rule_id}",
        "severity": severity,
        "location": "1.1",
    }


def test_flatten_list_of_lists_shape():
    """runner.all_responses 主形态: List[List[item]]"""
    responses = [
        [_make_item("R-1"), _make_item("R-2")],     # run 1
        [_make_item("R-3")],                          # run 2
    ]
    flat = _flatten_responses_to_items(responses)
    assert len(flat) == 3, f"应拍平 3 个 item, 实际 {len(flat)}: {flat}"
    rule_ids = sorted(it["rule_id"] for it in flat)
    assert rule_ids == ["R-1", "R-2", "R-3"]
    # 未带 id 字段, adapter 应自动补 r{idx}-i{j}
    for it in flat:
        assert "id" in it


def test_flatten_list_of_dicts_shape():
    """历史形态: List[{items: [...]}]"""
    responses = [
        {"items": [_make_item("R-1")]},
        {"items": [_make_item("R-2"), _make_item("R-3")]},
    ]
    flat = _flatten_responses_to_items(responses)
    assert len(flat) == 3
    rule_ids = sorted(it["rule_id"] for it in flat)
    assert rule_ids == ["R-1", "R-2", "R-3"]


def test_flatten_response_objects_shape():
    """_FakeResponse / UnifiedResponse-like: 取 .items 属性"""

    class _FakeResp:
        def __init__(self, items):
            self.items = items

    responses = [
        _FakeResp([_make_item("R-1")]),
        _FakeResp([_make_item("R-2")]),
    ]
    flat = _flatten_responses_to_items(responses)
    assert len(flat) == 2
    assert sorted(it["rule_id"] for it in flat) == ["R-1", "R-2"]


def test_flatten_empty():
    assert _flatten_responses_to_items([]) == []
    assert _flatten_responses_to_items(None) == []


def test_flatten_mixed_shapes():
    """同一批 responses 含 list / dict / 对象 三种形态混合 (实际不太会发生但要 robust)"""

    class _R:
        items = [_make_item("R-3")]

    responses = [
        [_make_item("R-1")],
        {"items": [_make_item("R-2")]},
        _R(),
    ]
    flat = _flatten_responses_to_items(responses)
    assert len(flat) == 3
    assert sorted(it["rule_id"] for it in flat) == ["R-1", "R-2", "R-3"]


def test_flatten_preserves_existing_id():
    """item 已有 id 字段时不应被覆盖"""
    responses = [[{"id": "ORIG-1", "rule_id": "R-1", "severity": "must"}]]
    flat = _flatten_responses_to_items(responses)
    assert flat[0]["id"] == "ORIG-1"


def test_flatten_maps_issue_to_problem_for_cuckoo_matching():
    """route_eval worker/advisor 输出常用 issue 字段, cuckoo scorer 匹配看 problem."""
    responses = [[{"id": "R-1", "issue": "字段缺失", "location": "3.1"}]]
    flat = _flatten_responses_to_items(responses)
    assert flat[0]["problem"] == "字段缺失"
    assert flat[0]["suggestion"] == ""
