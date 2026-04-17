"""
cuckoo_parser 覆盖测试 (Round 7)

cuckoo_parser 是评审报告到结构化 items 的解析入口,影响所有 eval 指标。
本文件:
- compute_confidence 全映射
- parse_review_report 三种策略分支 (YAML / Markdown / loose)
- _extract_fields_from_block 多种字段格式(含 **加粗**/纯文本)
- evidence_type 推断逻辑
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestComputeConfidence:
    def test_type_a(self):
        from cuckoo_parser import compute_confidence
        assert compute_confidence("A") == 0.9

    def test_type_b(self):
        from cuckoo_parser import compute_confidence
        assert compute_confidence("B") == 0.8

    def test_type_c(self):
        from cuckoo_parser import compute_confidence
        assert compute_confidence("C") == 0.5

    def test_empty_type(self):
        from cuckoo_parser import compute_confidence
        assert compute_confidence("") == 0.4

    def test_unknown_type_falls_back(self):
        from cuckoo_parser import compute_confidence
        assert compute_confidence("Z") == 0.4

    def test_none_input(self):
        from cuckoo_parser import compute_confidence
        assert compute_confidence(None) == 0.4

    def test_lowercase_normalized(self):
        from cuckoo_parser import compute_confidence
        assert compute_confidence("a") == 0.9

    def test_supplement_decay_applied(self):
        from cuckoo_parser import compute_confidence
        # 0.9 * 0.8 = 0.72
        assert compute_confidence("A", is_supplement=True) == 0.72

    def test_supplement_decay_with_c(self):
        from cuckoo_parser import compute_confidence
        # 0.5 * 0.8 = 0.4
        assert compute_confidence("C", is_supplement=True) == 0.4


class TestParseReviewReport:
    def test_yaml_style_single_item(self, tmp_path):
        from cuckoo_parser import parse_review_report
        report = tmp_path / "r.md"
        report.write_text(
            "- id: R-001\n"
            "  位置: 第 3 章 接口定义\n"
            "  问题: 缺少字段类型\n"
            "  建议: 补充 string/number 标注\n"
            "  严重度: must\n"
            "  依据类型: A\n"
            "  依据内容: [[PRD模板.md]]\n",
            encoding="utf-8",
        )
        items = parse_review_report(str(report))
        assert len(items) == 1
        item = items[0]
        assert item["id"] == "R-001"
        assert "接口定义" in item["location"]
        assert item["severity"] == "must"
        assert item["evidence_type"] == "A"
        assert item["confidence_score"] == 0.9

    def test_markdown_style_bold_fields(self, tmp_path):
        from cuckoo_parser import parse_review_report
        report = tmp_path / "r.md"
        report.write_text(
            "#### R-002\n"
            "- **位置**: 第 4.2 节\n"
            "- **问题**: 指标定义不清\n"
            "- **建议**: 给出公式\n"
            "- **严重度**: should\n"
            "- **依据类型**: B\n"
            "- **依据内容**: RC-101\n",
            encoding="utf-8",
        )
        items = parse_review_report(str(report))
        assert len(items) == 1
        item = items[0]
        assert item["id"] == "R-002"
        assert item["severity"] == "should"
        assert item["evidence_type"] == "B"
        assert item["confidence_score"] == 0.8

    def test_loose_fallback_when_no_block_format(self, tmp_path):
        """没有 #### 或 YAML,只有裸 R-XXX 也应该捞到."""
        from cuckoo_parser import parse_review_report
        report = tmp_path / "r.md"
        report.write_text(
            "一些介绍文字...\n"
            "R-003 建议补充错误码定义\n"
            "位置: 第 5 章\n"
            "严重度: must\n",
            encoding="utf-8",
        )
        items = parse_review_report(str(report))
        ids = {it["id"] for it in items}
        assert "R-003" in ids

    def test_duplicate_ids_deduplicated_markdown(self, tmp_path):
        """R-XXX 重复出现时只保留一条."""
        from cuckoo_parser import parse_review_report
        report = tmp_path / "r.md"
        report.write_text(
            "#### R-001\n- **位置**: foo\n- **问题**: bar\n\n"
            "#### R-001\n- **位置**: foo2\n- **问题**: bar2\n",
            encoding="utf-8",
        )
        items = parse_review_report(str(report))
        ids = [it["id"] for it in items]
        assert ids.count("R-001") == 1

    def test_multiple_items_preserved(self, tmp_path):
        from cuckoo_parser import parse_review_report
        report = tmp_path / "r.md"
        report.write_text(
            "#### R-001\n- **位置**: A\n- **问题**: a\n\n"
            "#### R-002\n- **位置**: B\n- **问题**: b\n\n"
            "#### R-003\n- **位置**: C\n- **问题**: c\n",
            encoding="utf-8",
        )
        items = parse_review_report(str(report))
        assert {it["id"] for it in items} == {"R-001", "R-002", "R-003"}


class TestExtractFieldsFromBlock:
    def test_bold_fields(self):
        from cuckoo_parser import _extract_fields_from_block
        block = (
            "- **位置**: 第 3 章\n"
            "- **问题**: 字段缺失\n"
            "- **建议**: 补充\n"
            "- **严重度**: must\n"
            "- **依据类型**: A\n"
            "- **依据内容**: [[foo.md]]\n"
        )
        item = _extract_fields_from_block("R-001", block)
        assert item["location"] == "第 3 章"
        assert item["problem"] == "字段缺失"
        assert item["severity"] == "must"
        assert item["evidence_type"] == "A"

    def test_plain_fields(self):
        from cuckoo_parser import _extract_fields_from_block
        block = (
            "位置：第 4 章\n"
            "问题：描述不清\n"
            "严重度：should\n"
            "依据类型：C\n"
        )
        item = _extract_fields_from_block("R-002", block)
        assert "第 4 章" in item["location"]
        assert item["severity"] == "should"
        assert item["evidence_type"] == "C"

    def test_evidence_type_inferred_from_wiki_link(self):
        """没标注 evidence_type 但依据含 [[页面]] → 推断为 A."""
        from cuckoo_parser import _extract_fields_from_block
        block = "- **依据**: 见 [[PRD模板.md]] 第 5 节\n"
        item = _extract_fields_from_block("R-001", block)
        assert item["evidence_type"] == "A"
        assert item["confidence_score"] == 0.9

    def test_evidence_type_inferred_from_rule_ref(self):
        from cuckoo_parser import _extract_fields_from_block
        block = "- **依据**: 参考规则 RC-042\n"
        item = _extract_fields_from_block("R-001", block)
        assert item["evidence_type"] == "B"

    def test_evidence_type_inferred_from_competitor(self):
        from cuckoo_parser import _extract_fields_from_block
        block = "- **依据**: 参考竞品 xxx 的做法\n"
        item = _extract_fields_from_block("R-001", block)
        assert item["evidence_type"] == "C"

    def test_problem_fallback_to_first_line(self):
        """没有"问题"字段 → 用首行作为 problem,去掉 R-XXX 前缀."""
        from cuckoo_parser import _extract_fields_from_block
        block = "R-042: 字段缺失的简述\n其他内容..."
        item = _extract_fields_from_block("R-042", block)
        # problem 去掉了 R-042 前缀
        assert "字段缺失的简述" in item["problem"]
        assert not item["problem"].startswith("R-")

    def test_raw_text_capped_at_500(self):
        from cuckoo_parser import _extract_fields_from_block
        block = "x" * 1000
        item = _extract_fields_from_block("R-001", block)
        assert len(item["raw_text"]) <= 500
