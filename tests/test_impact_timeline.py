"""impact_score 时序追加测试.

每次 update_rule_scores 触发 EMA 更新后,rule_impact_timeline.json 应追加
{ts, score, outcome, prd} 记录,供 dashboard 画轨迹曲线。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from feedback import _append_impact_timeline


class TestAppendImpactTimeline:
    def test_creates_file_on_first_call(self, tmp_path):
        """首次调用应创建 output/rule_impact_timeline.json."""
        updates = [
            {"rule_id": "V-02", "score": 0.525, "outcome": "effective_catch", "prd": "p1"},
        ]
        _append_impact_timeline(updates, str(tmp_path))

        out = tmp_path / "output" / "rule_impact_timeline.json"
        assert out.is_file()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "V-02" in data
        assert len(data["V-02"]) == 1
        assert data["V-02"][0]["score"] == 0.525
        assert data["V-02"][0]["outcome"] == "effective_catch"
        assert "ts" in data["V-02"][0]

    def test_appends_to_existing_file(self, tmp_path):
        """已有文件 → 追加到同一 rule 的 list 末尾."""
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        existing = {"V-02": [{"ts": "2026-04-01T10:00:00", "score": 0.5,
                              "outcome": "effective_catch", "prd": "p0"}]}
        (out_dir / "rule_impact_timeline.json").write_text(
            json.dumps(existing, ensure_ascii=False), encoding="utf-8",
        )

        _append_impact_timeline([
            {"rule_id": "V-02", "score": 0.47, "outcome": "wrong_rejection", "prd": "p1"},
        ], str(tmp_path))

        data = json.loads((out_dir / "rule_impact_timeline.json").read_text(encoding="utf-8"))
        assert len(data["V-02"]) == 2
        assert data["V-02"][1]["score"] == 0.47
        assert data["V-02"][1]["outcome"] == "wrong_rejection"

    def test_multiple_rules(self, tmp_path):
        """同一 session 多条 rule 更新应分别记录."""
        updates = [
            {"rule_id": "V-02", "score": 0.52, "outcome": "effective_catch", "prd": "p1"},
            {"rule_id": "RC-005", "score": 0.48, "outcome": "wrong_rejection", "prd": "p1"},
        ]
        _append_impact_timeline(updates, str(tmp_path))

        out = tmp_path / "output" / "rule_impact_timeline.json"
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "V-02" in data and "RC-005" in data
        assert data["V-02"][0]["score"] == 0.52
        assert data["RC-005"][0]["score"] == 0.48

    def test_corrupted_existing_file_resets(self, tmp_path):
        """已有文件 JSON 损坏 → 覆盖写入新数据,不崩."""
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        (out_dir / "rule_impact_timeline.json").write_text("{ broken json", encoding="utf-8")

        updates = [
            {"rule_id": "V-02", "score": 0.5, "outcome": "effective_catch", "prd": "p1"},
        ]
        _append_impact_timeline(updates, str(tmp_path))

        data = json.loads((out_dir / "rule_impact_timeline.json").read_text(encoding="utf-8"))
        assert "V-02" in data
        assert len(data["V-02"]) == 1
