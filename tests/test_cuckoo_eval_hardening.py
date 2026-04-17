"""
cuckoo_eval 加固测试 (Round 4)

覆盖:
- _safe_get: 缺失/非数值/None 的降级
- _atomic_write_json: 原子写 + rename 语义
- append_eval_history: 缺 key / 损坏历史文件 / 非 list 历史 的容忍
- print_eval_trend: 损坏 JSON 不抛
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestSafeGet:
    def test_returns_rounded_float(self):
        from cuckoo_eval import _safe_get
        # banker's rounding: 0.12345 可能 → 0.1234 或 0.1235,只校准到 4 位精度
        v = _safe_get({"k": 0.12345}, "k")
        assert abs(v - 0.1234) < 1e-3 or abs(v - 0.1235) < 1e-3

    def test_missing_key_default(self):
        from cuckoo_eval import _safe_get
        assert _safe_get({}, "k") == 0.0
        assert _safe_get({}, "k", default=1.0) == 1.0

    def test_non_dict_input(self):
        from cuckoo_eval import _safe_get
        assert _safe_get(None, "k") == 0.0
        assert _safe_get("not a dict", "k") == 0.0

    def test_non_numeric_value(self):
        from cuckoo_eval import _safe_get
        assert _safe_get({"k": "n/a"}, "k") == 0.0
        assert _safe_get({"k": None}, "k") == 0.0

    def test_int_is_coerced(self):
        from cuckoo_eval import _safe_get
        assert _safe_get({"k": 42}, "k") == 42.0


class TestAtomicWriteJson:
    def test_writes_and_replaces(self, tmp_path):
        from cuckoo_eval import _atomic_write_json
        target = tmp_path / "out.json"
        target.write_text("old content", encoding="utf-8")
        _atomic_write_json(str(target), {"new": True})
        assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}
        # tmp 文件不应残留
        assert not (tmp_path / "out.json.tmp").exists()

    def test_writes_to_fresh_path(self, tmp_path):
        from cuckoo_eval import _atomic_write_json
        target = tmp_path / "fresh.json"
        _atomic_write_json(str(target), [1, 2, 3])
        assert json.loads(target.read_text(encoding="utf-8")) == [1, 2, 3]


class TestAppendEvalHistory:
    def _full_scores(self):
        return {
            "overall_score": 0.72, "overall_verdict": "PARTIAL",
            "recall": 0.6, "precision": 0.8,
            "location_accuracy": 0.9, "evidence_reliability": 0.7,
            "severity_accuracy": 0.8, "format_completeness": 0.95,
            "detail": {"total_bugs": 10, "total_items": 12, "hit_count": 6},
        }

    def test_append_to_empty_dir_creates_file(self, tmp_path):
        from cuckoo_eval import append_eval_history
        entry = append_eval_history(str(tmp_path), "tc1", self._full_scores(), model="sonnet")
        assert entry["test_case"] == "tc1"
        assert entry["overall_score"] == 0.72
        # 文件落盘
        history_file = tmp_path / "output" / "eval_history.json"
        assert history_file.exists()
        data = json.loads(history_file.read_text(encoding="utf-8"))
        assert len(data) == 1

    def test_append_preserves_previous(self, tmp_path):
        from cuckoo_eval import append_eval_history
        append_eval_history(str(tmp_path), "tc1", self._full_scores())
        append_eval_history(str(tmp_path), "tc2", self._full_scores())
        history_file = tmp_path / "output" / "eval_history.json"
        data = json.loads(history_file.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert [h["test_case"] for h in data] == ["tc1", "tc2"]

    def test_corrupted_history_treated_as_empty(self, tmp_path):
        """损坏的 eval_history.json 不抛,当作空历史续写。"""
        from cuckoo_eval import append_eval_history
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "eval_history.json").write_text("not { valid json", encoding="utf-8")
        entry = append_eval_history(str(tmp_path), "tc", self._full_scores())
        assert entry["test_case"] == "tc"
        data = json.loads((output_dir / "eval_history.json").read_text(encoding="utf-8"))
        assert len(data) == 1

    def test_non_list_history_treated_as_empty(self, tmp_path):
        from cuckoo_eval import append_eval_history
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "eval_history.json").write_text('{"not": "a list"}', encoding="utf-8")
        append_eval_history(str(tmp_path), "tc", self._full_scores())
        data = json.loads((output_dir / "eval_history.json").read_text(encoding="utf-8"))
        assert isinstance(data, list) and len(data) == 1

    def test_missing_score_keys_do_not_crash(self, tmp_path):
        """scorer 返回降级结果 (只有 overall+verdict) 时,append 不 KeyError。"""
        from cuckoo_eval import append_eval_history
        degraded = {"overall_score": 0, "overall_verdict": "FAIL",
                    "reason": "scoring pipeline errored"}
        entry = append_eval_history(str(tmp_path), "tc", degraded)
        assert entry["overall_score"] == 0.0
        assert entry["overall_verdict"] == "FAIL"
        assert entry["recall"] == 0.0  # 缺失降级
        assert entry["detail"]["total_bugs"] == 0

    def test_scores_is_none_does_not_crash(self, tmp_path):
        from cuckoo_eval import append_eval_history
        entry = append_eval_history(str(tmp_path), "tc", None)
        assert entry["overall_verdict"] == "UNKNOWN"
        assert entry["recall"] == 0.0


class TestPrintEvalTrendResilience:
    def test_missing_file_no_op(self, tmp_path, capsys):
        from cuckoo_eval import print_eval_trend
        print_eval_trend(str(tmp_path))  # 不抛
        assert capsys.readouterr().out == ""

    def test_corrupted_file_no_op(self, tmp_path, capsys):
        """损坏的 history 不抛,trend 显示为空."""
        from cuckoo_eval import print_eval_trend
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "eval_history.json").write_text("corrupt", encoding="utf-8")
        print_eval_trend(str(tmp_path))  # 应 silent return
        assert "评测趋势对比" not in capsys.readouterr().out

    def test_non_list_file_no_op(self, tmp_path, capsys):
        from cuckoo_eval import print_eval_trend
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "eval_history.json").write_text('{"x": 1}', encoding="utf-8")
        print_eval_trend(str(tmp_path))
        assert "评测趋势对比" not in capsys.readouterr().out
