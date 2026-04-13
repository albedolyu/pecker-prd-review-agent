"""
Integration tests — 验证各模块间数据流是否正确衔接。
不调用真实 API，所有测试使用 tmp_path fixture 构造临时工作目录。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from parallel_review import merge_and_deduplicate
from parallel_review import verify_evidence as parallel_verify_evidence
from shrike_review import shrike_review
from cuckoo_parser import parse_review_report
from cuckoo_scorer import (
    match_items_to_bugs,
    verify_evidence as cuckoo_verify_evidence,
    calculate_scores,
)
from kakapo_dream import scan_wiki_health, auto_fix


# ============================================================
# 共用工厂函数
# ============================================================

def _make_item(
    id, location, issue, suggestion,
    severity="should", evidence_type="B",
    evidence_content="RC-005 格式规范",
    dimension="结构层",
):
    """构造一条 parallel_review 格式的改进项"""
    return {
        "id": id,
        "location": location,
        "issue": issue,
        "suggestion": suggestion,
        "severity": severity,
        "evidence_type": evidence_type,
        "evidence_content": evidence_content,
        "dimension": dimension,
    }


def _write(path, content):
    """写文件，自动创建父目录"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ============================================================
# 合规 wiki 页面模板（满足伯劳 Gate 3 三个条件）
# ============================================================

_VALID_WIKI_PAGE = """\
---
source: 测试
created: 2026-01-01
updated: 2026-04-01
tags: [test]
---

# 测试页面

这是用于集成测试的 wiki 页面内容。

相关参考：[[概念-企业查询]]
"""


# ============================================================
# Test 1: parallel_review → shrike_review 数据流
# ============================================================

class TestParallelToShrikePipeline:
    """
    验证：一份格式合规的改动报告 + 合规 wiki 页面
    能够通过伯劳全部五关检查。
    """

    def _build_workspace(self, tmp_path):
        ws = tmp_path / "workspace"
        output_dir = ws / "output"
        wiki_dir = ws / "wiki"
        output_dir.mkdir(parents=True)
        wiki_dir.mkdir(parents=True)

        # Gate 3：合规 wiki 页面（前缀合法 + frontmatter + 双向链接）
        _write(
            str(wiki_dir / "概念-企业查询.md"),
            _VALID_WIKI_PAGE,
        )

        # Gate 1 + Gate 5：包含所有必须章节 + R-001 条目含必填字段
        report_content = """\
# PRD 改动报告

## 评审概览

本次评审共发现 1 条改进项。

## 已确认改进项

#### R-001 缺少成功标准

- **位置**：3.2 功能说明
- **问题**：搜索结果未定义成功标准
- **建议**：增加可量化的成功指标
- **严重度**：must
- **依据**：RC-005 格式规范

## 待确定事项

暂无。

## 已驳回

暂无。

## 人工复核提醒

请确认 R-001 的改进是否已落实。
"""
        _write(
            str(output_dir / "PRD_改动报告_20260412.md"),
            report_content,
        )

        return str(ws)

    def test_shrike_passes_on_well_formed_workspace(self, tmp_path):
        """合规的 workspace 应通过伯劳全部五关"""
        workspace = self._build_workspace(tmp_path)
        result = shrike_review(workspace)

        # Gate 1：报告完整性
        assert result["gates"]["report_completeness"]["passed"], (
            "Gate 1 失败: " + str(result["gates"]["report_completeness"]["details"])
        )
        # Gate 3：wiki 质量
        assert result["gates"]["wiki_quality"]["passed"], (
            "Gate 3 失败: " + str(result["gates"]["wiki_quality"]["details"])
        )
        # Gate 4：安全扫描
        assert result["gates"]["security_scan"]["passed"], (
            "Gate 4 失败: " + str(result["gates"]["security_scan"]["details"])
        )
        # Gate 5：格式规范
        assert result["gates"]["format_compliance"]["passed"], (
            "Gate 5 失败: " + str(result["gates"]["format_compliance"]["details"])
        )
        # 总体通过
        assert result["verdict"] == "PASS", (
            f"伯劳判定 FAIL，通过 {result['passed']}/{result['total']} 关"
        )


# ============================================================
# Test 2: cuckoo_eval 完整 pipeline
# ============================================================

class TestCuckooEvalPipeline:
    """
    验证：parse_review_report → match_items_to_bugs →
          cuckoo_verify_evidence → calculate_scores
    三条改进项中有 2 条命中预埋 bug，recall = 1.0，precision > 0。
    """

    _REPORT_CONTENT = """\
## 评审概览

共 3 条改进项。

## 已确认改进项

#### R-001 搜索结果排序方向矛盾

- **位置**：3.7 搜索结果
- **问题**：排序说明前后矛盾，第一段说从晚到早，后文说从早到晚
- **建议**：统一排序方向定义，在 3.7 节明确标注
- **严重度**：must
- **依据类型**：B
- **依据**：RC-005 格式规范

#### R-002 字段类型未定义

- **位置**：4.2 数据字段
- **问题**：注册资本字段类型不明确，前端无法确定用 string 还是 number
- **建议**：在字段 DDL 中明确 DECIMAL(18,2) 类型
- **严重度**：should
- **依据类型**：A
- **依据**：[[概念-企业查询]] 业务字段规范

#### R-003 成功标准缺失

- **位置**：5.1 成功指标
- **问题**：未定义可量化的成功标准
- **建议**：增加 DAU / 转化率等量化指标
- **严重度**：should
- **依据类型**：B
- **依据**：RC-007 SMART 验证规范
"""

    def _build_workspace(self, tmp_path):
        ws = tmp_path / "cuckoo_ws"
        wiki_dir = ws / "wiki"
        rules_dir = ws / "review-rules"
        wiki_dir.mkdir(parents=True)
        rules_dir.mkdir(parents=True)

        # A 类依据需要的 wiki 页面
        _write(str(wiki_dir / "概念-企业查询.md"), _VALID_WIKI_PAGE)

        # B 类依据需要的规则文件（包含 RC-005 和 RC-007）
        _write(
            str(rules_dir / "review-checklist.md"),
            "# Review Checklist\n\nRC-005 格式规范\n\nRC-007 SMART 验证规范\n",
        )

        return str(ws)

    def _build_report_file(self, tmp_path):
        report_path = tmp_path / "PRD_改动报告_20260412.md"
        _write(str(report_path), self._REPORT_CONTENT)
        return str(report_path)

    def _build_test_case(self):
        """预埋 2 个 bug，匹配 R-001 和 R-002"""
        return {
            "name": "集成测试用例",
            "planted_bugs": [
                {
                    "id": "BUG-001",
                    "location": "3.7",
                    "type": "不一致",
                    "severity": "must",
                    "description": "排序方向自相矛盾",
                    "keywords": ["排序", "从晚到早"],
                },
                {
                    "id": "BUG-002",
                    "location": "4.2",
                    "type": "字段类型",
                    "severity": "should",
                    "description": "注册资本字段类型未定义",
                    "keywords": ["字段", "类型", "注册资本"],
                },
            ],
            "non_issues": [],
        }

    def test_full_cuckoo_pipeline(self, tmp_path):
        """完整跑一遍 cuckoo eval pipeline，验证 recall=1.0，precision>0"""
        workspace = self._build_workspace(tmp_path)
        report_path = self._build_report_file(tmp_path)
        test_case = self._build_test_case()

        # Step 1: 解析报告
        review_items = parse_review_report(report_path)
        assert len(review_items) == 3, f"期望解析到 3 条改进项，实际: {len(review_items)}"

        # Step 2: 匹配预埋 bug
        planted_bugs = test_case["planted_bugs"]
        matches = match_items_to_bugs(review_items, planted_bugs)

        assert len(matches["hits"]) == 2, (
            f"期望命中 2 个预埋 bug，实际: {len(matches['hits'])}"
        )
        assert len(matches["misses"]) == 0, (
            f"期望无漏报，实际漏报: {[b['id'] for b in matches['misses']]}"
        )

        # Step 3: 依据验证（使用 cuckoo_eval 的 verify_evidence）
        verified_count, failed_count, ev_details = cuckoo_verify_evidence(
            review_items, workspace
        )
        evidence_results = (verified_count, failed_count, ev_details)

        # R-001 (B类 RC-005) 和 R-002 (A类 wiki) 应通过；R-003 (B类 RC-007) 应通过
        # 至少有 2 条验证通过
        assert verified_count >= 2, (
            f"期望至少 2 条依据验证通过，实际: {verified_count}"
        )

        # Step 4: 计算评分
        scores = calculate_scores(matches, evidence_results, review_items)

        # 召回率：2/2 bug 均命中
        assert scores["recall"] == 1.0, f"recall 期望 1.0，实际: {scores['recall']}"

        # 精确率：2 真阳 / (2 真阳 + 1 误报) = 0.667
        assert scores["precision"] > 0, (
            f"precision 期望 > 0，实际: {scores['precision']}"
        )

        # 综合verdict 至少 PARTIAL
        assert scores["overall_verdict"] in ("PASS", "PARTIAL"), (
            f"综合得分过低: {scores['overall_score']:.1%}, verdict: {scores['overall_verdict']}"
        )


# ============================================================
# Test 3: kakapo 健康扫描 + dry-run 修复
# ============================================================

class TestKakapoHealthAndFix:
    """
    验证：scan_wiki_health 能检测到断链和缺 frontmatter，
    auto_fix(dry_run=True) 返回非空变更列表。
    """

    def _build_wiki(self, tmp_path):
        wiki_dir = tmp_path / "kakapo_wiki"
        wiki_dir.mkdir()

        # 页面 A：有合规前缀 + frontmatter，但引用了不存在的页面（产生断链）
        _write(
            str(wiki_dir / "概念-搜索功能.md"),
            """\
---
source: 测试
created: 2026-01-01
updated: 2026-04-01
tags: [test]
---

# 搜索功能

企业搜索的核心流程。

相关：[[不存在的页面]]
""",
        )

        # 页面 B：缺少 frontmatter（无 --- 开头）
        _write(
            str(wiki_dir / "概念-风险信息.md"),
            """\
# 风险信息

描述企业的司法风险和行政处罚记录。

相关：[[概念-搜索功能]]
""",
        )

        return str(wiki_dir)

    def test_scan_detects_issues(self, tmp_path):
        """scan_wiki_health 应检测到断链和缺 frontmatter"""
        wiki_dir = self._build_wiki(tmp_path)
        report = scan_wiki_health(wiki_dir)

        # 应检测到至少 1 条断链（[[不存在的页面]]）
        assert len(report["broken_links"]) >= 1, (
            f"期望至少 1 条断链，实际: {report['broken_links']}"
        )
        broken_targets = [item["target"] for item in report["broken_links"]]
        assert "不存在的页面" in broken_targets, (
            f"期望检测到 [[不存在的页面]]，实际断链: {broken_targets}"
        )

        # 应检测到至少 1 个缺 frontmatter 的页面
        assert len(report["missing_frontmatter"]) >= 1, (
            f"期望至少 1 页缺 frontmatter，实际: {report['missing_frontmatter']}"
        )
        fm_files = [item["file"] for item in report["missing_frontmatter"]]
        assert "概念-风险信息.md" in fm_files, (
            f"期望 概念-风险信息.md 缺 frontmatter，实际: {fm_files}"
        )

    def test_auto_fix_dry_run_returns_changes(self, tmp_path):
        """auto_fix(dry_run=True) 应返回非空变更列表，但不实际创建文件"""
        wiki_dir = self._build_wiki(tmp_path)
        report = scan_wiki_health(wiki_dir)

        changes = auto_fix(wiki_dir, report, dry_run=True)

        assert len(changes) > 0, "dry_run 模式下应返回至少 1 条变更记录"

        # 所有变更都应带 dry_run=True 标记（命名建议例外，无该字段）
        for change in changes:
            if change["type"] != "naming_suggestion":
                assert change.get("dry_run") is True, (
                    f"非命名建议的变更应有 dry_run=True: {change}"
                )

        # 干跑不应真正创建占位文件
        placeholder = os.path.join(wiki_dir, "不存在的页面.md")
        assert not os.path.exists(placeholder), (
            "dry_run=True 不应创建实际文件"
        )


# ============================================================
# Test 4: merge_and_deduplicate → parallel_verify_evidence
# ============================================================

class TestMergeDeduplicateThenVerify:
    """
    验证：6 条改进项（含 1 对重复）经 merge_and_deduplicate 后
    数量减少 1；再跑 parallel_review.verify_evidence 后
    至少有 1 条 VERIFIED。
    """

    def _make_worker_items(self):
        """
        构造 2 个 worker 各 3 条的改进项，其中有 1 对高度相似（近重复）。
        Worker-1: item-a (must), item-b, item-c
        Worker-2: item-a' (should, 和 item-a 近重复), item-d, item-e
        预期去重后剩 5 条（保留 severity 更高的 must 版本）。
        """
        # Worker-1
        w1_a = _make_item(
            "W1-001", "3.2 功能说明", "搜索结果缺少成功标准",
            "增加可量化指标", severity="must",
            evidence_type="B", evidence_content="RC-005 格式规范",
        )
        w1_b = _make_item(
            "W1-002", "4.1 字段定义", "注册资本字段类型不明确",
            "明确 DECIMAL 类型", severity="should",
            evidence_type="B", evidence_content="RC-009 字段映射规范",
        )
        w1_c = _make_item(
            "W1-003", "2.3 术语定义", "法人定义未对齐业务规范",
            "引用标准定义", severity="should",
            evidence_type="B", evidence_content="RC-005 格式规范",
        )

        # Worker-2 — item-a' 和 w1_a 高度相似
        w2_a_prime = _make_item(
            "W2-001", "3.2 功能说明", "搜索结果缺少成功标准（重复）",
            "增加可量化的成功指标", severity="should",
            evidence_type="B", evidence_content="RC-005 格式规范",
        )
        w2_d = _make_item(
            "W2-002", "5.1 边界条件", "并发请求未定义限流策略",
            "增加 QPM 上限说明", severity="must",
            evidence_type="B", evidence_content="RC-009 字段映射规范",
        )
        w2_e = _make_item(
            "W2-003", "6.0 权限控制", "未说明 C 端用户角色权限",
            "补充 RBAC 权限矩阵", severity="should",
            evidence_type="B", evidence_content="RC-009 字段映射规范",
        )

        return [w1_a, w1_b, w1_c, w2_a_prime, w2_d, w2_e]

    def _build_workspace(self, tmp_path):
        ws = tmp_path / "merge_ws"
        wiki_dir = ws / "wiki"
        rules_dir = ws / "review-rules"
        wiki_dir.mkdir(parents=True)
        rules_dir.mkdir(parents=True)

        # 规则文件包含 RC-005 和 RC-009
        _write(
            str(rules_dir / "review-checklist.md"),
            "# Review Checklist\n\nRC-005 格式规范\n\nRC-009 字段映射规范\n",
        )
        # wiki 页面（B 类依据不需要 wiki，但保留以防万一）
        _write(str(wiki_dir / "概念-企业查询.md"), _VALID_WIKI_PAGE)

        return str(ws)

    def test_merge_reduces_count_by_one(self, tmp_path):
        """6 条 items 含 1 对重复，去重后应剩 5 条"""
        items = self._make_worker_items()
        assert len(items) == 6

        merged = merge_and_deduplicate(items)

        assert len(merged) == 5, (
            f"期望去重后 5 条，实际: {len(merged)}\n"
            f"保留项: {[(i['id'], i['issue'][:20]) for i in merged]}"
        )

    def test_merge_keeps_higher_severity(self, tmp_path):
        """去重时应保留 severity=must 的版本（w1_a），丢弃 should 版本"""
        items = self._make_worker_items()
        merged = merge_and_deduplicate(items)

        # 找到 "搜索结果缺少成功标准" 相关的那条
        target = next(
            (i for i in merged if "搜索结果缺少成功标准" in i.get("issue", "")), None
        )
        assert target is not None, "去重后应还存在 '搜索结果缺少成功标准' 这条"
        assert target["severity"] == "must", (
            f"去重后应保留 must 版本，实际: {target['severity']}"
        )

    def test_verify_evidence_returns_verified(self, tmp_path):
        """经 merge 后的 items，verify_evidence 应至少有 1 条 VERIFIED"""
        items = self._make_worker_items()
        merged = merge_and_deduplicate(items)
        workspace = self._build_workspace(tmp_path)

        verified_items = parallel_verify_evidence(merged, workspace)

        verified_count = sum(1 for i in verified_items if i.get("status") == "VERIFIED")
        assert verified_count > 0, (
            f"期望至少 1 条 VERIFIED，实际全部状态: "
            f"{[i.get('status') for i in verified_items]}"
        )

    def test_merge_then_verify_pipeline(self, tmp_path):
        """端到端：merge → verify，验证 VERIFIED 数量符合预期"""
        items = self._make_worker_items()
        workspace = self._build_workspace(tmp_path)

        # 合并
        merged = merge_and_deduplicate(items)
        assert len(merged) == 5

        # 验证依据（所有 B 类条目引用 RC-005 或 RC-009，均在 review-rules 中）
        verified_items = parallel_verify_evidence(merged, workspace)

        statuses = [i.get("status") for i in verified_items]
        verified_count = statuses.count("VERIFIED")
        retracted_count = statuses.count("RETRACTED")

        # RC-005 和 RC-009 都在规则文件里，预期全部通过
        assert verified_count == 5, (
            f"期望 5 条 VERIFIED，实际: VERIFIED={verified_count}, "
            f"RETRACTED={retracted_count}"
        )


class TestSessionResumeNoDuplication:
    """回归测试：进程重启后 resume → save 不应重复写入旧历史"""

    def test_resume_save_resume_no_duplication(self, tmp_path):
        """模拟完整的 重启→恢复→继续→再重启→恢复 场景"""
        from security import save_session_turn, resume_session, _last_saved_count

        output_dir = tmp_path
        sessions_dir = output_dir / ".sessions"
        sessions_dir.mkdir()
        sf = str(sessions_dir / "reviewer_prd.jsonl")

        # 第一个进程：保存 4 条消息
        msgs = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
            {"role": "user", "content": "msg3"},
            {"role": "assistant", "content": "msg4"},
        ]
        save_session_turn(sf, msgs, {"turn": "init"})

        # 模拟进程重启
        _last_saved_count.clear()

        # 第二个进程：恢复
        restored, _ = resume_session(str(output_dir), "prd")
        assert restored is not None
        assert len(restored) == 4

        # 加 2 条新消息并保存（不手动同步 _last_saved_count）
        restored.append({"role": "user", "content": "msg5"})
        restored.append({"role": "assistant", "content": "msg6"})
        save_session_turn(sf, restored, {"turn": "interact"})

        # 模拟再次重启
        _last_saved_count.clear()

        # 第三个进程：再次恢复 — 应该正好 6 条，无重复
        restored2, _ = resume_session(str(output_dir), "prd")
        assert len(restored2) == 6, f"Expected 6, got {len(restored2)} (duplication bug!)"
        contents = [m["content"] for m in restored2]
        assert contents == ["msg1", "msg2", "msg3", "msg4", "msg5", "msg6"]
